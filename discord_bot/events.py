"""Discord webhook events (Webhook Events URL: POST /discord/events).

When the bot is added to a server Discord sends APPLICATION_AUTHORIZED with the
server, and the bot posts a short setup guide there: in the server's system
channel (where "X joined" messages go), or else the first text channel it may
write in. Requests are signed like interactions; Discord wants an empty 204
within 3 seconds, so the message is sent in the background.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

import scheduler

from . import client
from .interactions import verify_request

logger = logging.getLogger('aicr.discord')
router = APIRouter(tags=['discord'])

PING, EVENT = 0, 1
GUILD_INSTALL = 0
TEXT_CHANNEL = 0
MAX_CHANNELS_TRIED = 5


def welcome_text() -> str:
    return (
        "👋 **Thanks for adding AI CR!** It answers exam questions and posts exam updates, one channel per class.\n\n"
        "**Set it up (someone with Manage Channels):**\n"
        "1. Go to a class's channel and run `/setup name:<class name>`. Add `cr_role:` to choose the CR role.\n"
        "2. A CR runs `/manage` there to open the editor and add the courses and exams.\n"
        "3. Repeat in each class's channel — every channel is its own class.\n\n"
        "**Then everyone can use** `/next-week-update`, `/this-week-update`, `/next-exam-day-update`, "
        "`/next-exam-notes`, `/exams` and `/ask`. When a CR runs an update command, it's posted for everyone.\n\n"
        f"Every Friday at {scheduler.weekly_time():%H:%M} I post next week's exams, and at "
        f"{scheduler.reminder_time():%H:%M} the evening before an exam day I post that day's exams (Bangladesh time)."
    )


def _candidate_channels(guild: dict) -> list[str]:
    candidates = [str(guild['system_channel_id'])] if guild.get('system_channel_id') else []
    try:
        channels = client.request('GET', f"/guilds/{guild['id']}/channels") or []
    except client.DiscordError as error:
        logger.warning('could not list channels of server %s: %s', guild.get('id'), error)
        channels = []
    text = sorted((c for c in channels if c.get('type') == TEXT_CHANNEL), key=lambda c: c.get('position', 0))
    candidates += [str(c['id']) for c in text if str(c['id']) not in candidates]
    return candidates[:MAX_CHANNELS_TRIED]


def send_welcome(guild: dict) -> str | None:
    """Post the setup guide in the first channel that accepts it. Returns that channel id."""
    for channel_id in _candidate_channels(guild):
        try:
            client.post_messages(channel_id, [welcome_text()])
        except client.DiscordError as error:
            if error.permanent:
                continue  # no access to this channel: try the next one
            logger.warning('welcome for server %s not sent: %s', guild.get('id'), error)
            return None
        logger.info('welcome posted in server %s, channel %s', guild.get('id'), channel_id)
        return channel_id
    logger.warning('welcome for server %s not sent: no channel the bot can write in', guild.get('id'))
    return None


@router.post('/discord/events')
async def events(request: Request, background_tasks: BackgroundTasks) -> Response:
    body = await request.body()
    if not verify_request(body, request.headers.get('X-Signature-Ed25519', ''),
                          request.headers.get('X-Signature-Timestamp', '')):
        raise HTTPException(status_code=401, detail='invalid request signature')
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail='invalid JSON') from error

    event = payload.get('event') or {}
    data = event.get('data') or {}
    if (payload.get('type') == EVENT and event.get('type') == 'APPLICATION_AUTHORIZED'
            and data.get('integration_type') == GUILD_INSTALL and (data.get('guild') or {}).get('id')):
        background_tasks.add_task(send_welcome, data['guild'])
    return Response(status_code=204)
