"""Discord slash commands over HTTP (Interactions Endpoint URL: POST /discord/interactions).

Discord needs an answer within 3 seconds, so every command is acknowledged at
once with "thinking…" (only the person who ran it sees it), and the real answer
is filled in by a background task. The channel a command is run in decides the
class; a thread counts as its parent channel.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

import date_ranges as dr
import db_fetch
import links
import scheduler
import updates
from Chatbot.Chatbot import answer
from Chatbot.formatter import DB_ERROR_TEXT, GENERIC_ERROR_TEXT

from . import client

logger = logging.getLogger('aicr.discord')
router = APIRouter(tags=['discord'])

PING, APPLICATION_COMMAND = 1, 2
PONG, DEFERRED_MESSAGE = 1, 5
ADMINISTRATOR, MANAGE_CHANNELS, MANAGE_GUILD = 1 << 3, 1 << 4, 1 << 5
THREAD_TYPES = {10, 11, 12}
MAX_CLOCK_SKEW_SECONDS = 300

NOT_SET_UP = ("This channel isn't linked to a class yet. Someone with the **Manage Channels** permission "
              "can run `/setup` here.")


# ---------------------------------------------------------------------------
# Request verification
# ---------------------------------------------------------------------------
def _verify_key() -> VerifyKey:
    key = os.getenv('DISCORD_PUBLIC_KEY', '')
    if not key:
        raise HTTPException(status_code=503, detail='DISCORD_PUBLIC_KEY is not set')
    return VerifyKey(bytes.fromhex(key))


def verify_request(body: bytes, signature: str, timestamp: str) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > MAX_CLOCK_SKEW_SECONDS:
            return False
        _verify_key().verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


@router.post('/discord/interactions')
async def interactions(request: Request, background_tasks: BackgroundTasks) -> dict:
    body = await request.body()
    if not verify_request(body, request.headers.get('X-Signature-Ed25519', ''),
                          request.headers.get('X-Signature-Timestamp', '')):
        raise HTTPException(status_code=401, detail='invalid request signature')
    try:
        interaction = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail='invalid JSON') from error

    if interaction.get('type') == PING:
        return {'type': PONG}
    if interaction.get('type') != APPLICATION_COMMAND:
        raise HTTPException(status_code=400, detail='unsupported interaction')

    background_tasks.add_task(run_command, interaction)
    return {'type': DEFERRED_MESSAGE, 'data': {'flags': client.EPHEMERAL}}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@dataclass
class Context:
    command: str
    options: dict
    guild_id: str | None
    channel_id: str              # the class's channel (a thread's parent)
    reply_channel_id: str        # where the command was run (may be a thread)
    user_id: str
    permissions: int
    roles: list[str]


@dataclass
class Answer:
    messages: list[str]
    components: list | None = None


def context_of(interaction: dict) -> Context:
    data = interaction.get('data') or {}
    member = interaction.get('member') or {}
    user = member.get('user') or interaction.get('user') or {}
    channel = interaction.get('channel') or {}
    channel_id = interaction.get('channel_id') or channel.get('id') or ''
    if channel.get('type') in THREAD_TYPES and channel.get('parent_id'):
        channel_id = channel['parent_id']  # a thread belongs to its channel's class
    return Context(
        command=data.get('name', ''),
        options={o['name']: o.get('value') for o in data.get('options') or []},
        guild_id=interaction.get('guild_id'),
        channel_id=str(channel_id),
        reply_channel_id=str(interaction.get('channel_id') or channel_id),
        user_id=str(user.get('id', '')),
        permissions=int(member.get('permissions') or 0),
        roles=[str(r) for r in member.get('roles') or []],
    )


def is_channel_admin(ctx: Context) -> bool:
    return bool(ctx.permissions & (ADMINISTRATOR | MANAGE_CHANNELS | MANAGE_GUILD))


def is_cr(ctx: Context, cls: dict) -> bool:
    """CRs: anyone who can manage the channel, plus members of the class's CR role."""
    return is_channel_admin(ctx) or bool(cls.get('cr_role_id') and cls['cr_role_id'] in ctx.roles)


def run_command(interaction: dict) -> None:
    token = interaction.get('token', '')
    ctx = context_of(interaction)
    started = time.perf_counter()
    outcome = 'ok'
    try:
        result = dispatch(ctx)
    except db_fetch.DatabaseError as error:
        outcome = 'db_error'
        logger.error('database error in /%s: code=%s status=%s', ctx.command, error.code, error.status)
        result = Answer([DB_ERROR_TEXT])
    except Exception:
        outcome = 'error'
        logger.exception('unexpected error in /%s', ctx.command)
        result = Answer([GENERIC_ERROR_TEXT])
    try:
        client.reply(token, result.messages, ephemeral=True, components=result.components)
    except client.DiscordError as error:
        logger.error('could not deliver /%s reply: %s', ctx.command, error)
    logger.info('discord command=/%s outcome=%s total_ms=%.0f', ctx.command, outcome,
                (time.perf_counter() - started) * 1000)


def dispatch(ctx: Context) -> Answer:
    if not ctx.guild_id:
        return Answer(["Use this in your class's channel on the server."])
    if ctx.command == 'setup':
        return setup(ctx)

    cls = db_fetch.fetch_class_by_channel(ctx.channel_id)
    if cls is None:
        return Answer([NOT_SET_UP])
    now = dr.now_local()

    builders = {
        'next-week-update': lambda: updates.week_update(cls['id'], 'next', now),
        'this-week-update': lambda: updates.week_update(cls['id'], 'this', now),
        'next-exam-day-update': lambda: updates.next_exam_day_update(cls['id'], now),
        'next-exam-notes': lambda: updates.next_exam_day_update(cls['id'], now, notes_only=True),
    }
    if ctx.command in builders:
        update = builders[ctx.command]()
        if is_cr(ctx, cls):
            return post_for_everyone(ctx, cls, update)
        return Answer(update.messages)
    if ctx.command == 'exams':
        return Answer([f"📋 Upcoming exams for **{updates.escape(cls['name'])}** — dates, times, syllabus and notes."],
                      client.link_button('Open exam list', links.board_url(cls['view_key'])))
    if ctx.command == 'manage':
        return manage(ctx, cls)
    if ctx.command == 'ask':
        question = str(ctx.options.get('question') or '')
        return Answer(answer(question, class_id=cls['id']).messages)
    return Answer(['Unknown command. It may have been removed; try again in a minute.'])


POST_COOLDOWN_SECONDS = 20
_recent_posts: dict[tuple[str, str], float] = {}


def post_for_everyone(ctx: Context, cls: dict, update: updates.Update) -> Answer:
    """A CR's update goes into the channel; the CR gets a private confirmation."""
    key = (ctx.reply_channel_id, ctx.command)
    if time.monotonic() - _recent_posts.get(key, -1e9) < POST_COOLDOWN_SECONDS:
        return Answer(['That update was just posted here. Wait a few seconds to post it again.'])
    _recent_posts[key] = time.monotonic()
    try:
        client.post_messages(ctx.reply_channel_id, update.messages)
    except client.DiscordError as error:
        _recent_posts.pop(key, None)
        logger.warning('class %s: /%s not posted: %s', cls['id'], ctx.command, error)
        return Answer([f'Not posted: {error.friendly()} Here it is just for you:', *update.messages])
    exams = f"{update.exam_count} exam{'s' if update.exam_count != 1 else ''}"
    return Answer([f'✅ Posted in the channel for everyone ({exams}).'])


def manage(ctx: Context, cls: dict) -> Answer:
    if not is_cr(ctx, cls):
        role = f"the <@&{cls['cr_role_id']}> role or " if cls.get('cr_role_id') else ''
        return Answer([f'Only CRs can edit exams. CRs are members with {role}the **Manage Channels** permission. '
                       'Use `/exams` to see the exam list.'])
    try:
        token = links.make_editor_token(cls['id'], ctx.user_id)
    except links.LinksMisconfigured:
        logger.error('EDITOR_LINK_SECRET is not set; cannot issue editor links')
        return Answer(['The editor is not configured on the server yet (EDITOR_LINK_SECRET is missing).'])
    hours = links.ttl_hours()
    valid = f'{hours:g} hour{"s" if hours != 1 else ""}'
    return Answer(
        [f"✏️ Editor for **{updates.escape(cls['name'])}**. Only you can see this link, and it works for {valid}. "
         "Don't share it — anyone with it can edit this class's exams. Run `/manage` again for a fresh one."],
        client.link_button('Open CR editor', links.editor_url(token)),
    )


def setup(ctx: Context) -> Answer:
    if not is_channel_admin(ctx):
        return Answer(['Only members with the **Manage Channels** permission can set up a class.'])
    name = ' '.join(str(ctx.options.get('name') or '').split())
    if not 2 <= len(name) <= 100:
        return Answer(['The class name must be 2–100 characters.'])
    changes: dict = {'name': name}
    if ctx.options.get('cr_role'):
        changes['cr_role_id'] = db_fetch.snowflake(ctx.options['cr_role'])
    if ctx.options.get('auto_updates') is not None:
        changes['auto_updates'] = bool(ctx.options['auto_updates'])

    existing = db_fetch.fetch_class_by_channel(ctx.channel_id)
    inactive = None if existing else db_fetch.fetch_inactive_class_by_channel(ctx.channel_id)
    if existing:
        cls = db_fetch.update_class(existing['id'], changes)
        verb = 'updated'
    elif inactive:
        # The bot was removed from this server (or lost the channel) and is back.
        cls = db_fetch.reactivate_class(inactive['id'], {**changes, 'discord_guild_id': db_fetch.snowflake(ctx.guild_id)})
        verb = 'restored with its earlier courses and exams'
    elif ctx.options.get('use_existing_data'):
        cls = None
        for candidate in db_fetch.fetch_unlinked_classes():
            cls = db_fetch.update_class(candidate['id'], {
                **changes, 'discord_guild_id': db_fetch.snowflake(ctx.guild_id),
                'discord_channel_id': db_fetch.snowflake(ctx.channel_id),
            }, only_if_unlinked=True)
            if cls:
                break
        if cls is None:
            return Answer(['There is no earlier data waiting to be linked. Run `/setup` without '
                           '`use_existing_data` to start this class fresh.'])
        verb = 'linked to the earlier courses and exams'
    else:
        try:
            cls = db_fetch.create_class(name=name, guild_id=ctx.guild_id, channel_id=ctx.channel_id,
                                        cr_role_id=changes.get('cr_role_id'))
        except db_fetch.DatabaseError as error:
            if error.code != 'duplicate':
                raise
            return Answer(['This channel was just set up by someone else. Run `/setup` again to change it.'])
        if 'auto_updates' in changes:
            cls = db_fetch.update_class(cls['id'], {'auto_updates': changes['auto_updates']})
        verb = 'set up'
    if cls is None:
        return Answer(['That class could not be found any more. Please run `/setup` again.'])

    crs = f"<@&{cls['cr_role_id']}> and members" if cls.get('cr_role_id') else 'Members'
    schedule = (f"Every Friday at {scheduler.weekly_time():%H:%M} I post next week's exams, and at "
                f"{scheduler.reminder_time():%H:%M} the day before an exam day I post that day's exams (Bangladesh time)."
                if cls.get('auto_updates') else 'Automatic updates are **off** for this channel.')
    return Answer([
        f"✅ This channel is now **{updates.escape(cls['name'])}** ({verb}).\n\n"
        "**Everyone:** `/next-week-update`, `/this-week-update`, `/next-exam-day-update`, `/next-exam-notes`, "
        "`/exams`, `/ask`\n"
        f"**CRs** ({crs} with Manage Channels): the four update commands post for everyone, and `/manage` "
        f"opens the editor.\n\n{schedule}"
    ], client.link_button('Open exam list', links.board_url(cls['view_key'])))
