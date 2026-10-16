"""Minimal Discord REST client (no gateway connection needed).

The bot only ever: posts messages in a class channel (bot token), answers slash
commands through the interaction webhook (interaction token, no bot token), and
registers its commands. Every message disables mentions, so text a CR typed
can never ping @everyone or a role.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger('aicr.discord')

API_BASE = 'https://discord.com/api/v10'
USER_AGENT = 'DiscordBot (https://ai-cr.onrender.com, 2.0)'  # Discord requires this format
TIMEOUT_SECONDS = 15
NO_MENTIONS = {'parse': []}
EPHEMERAL = 1 << 6

# Discord JSON error codes worth explaining to a CR.
MISSING_ACCESS = 50001
MISSING_PERMISSIONS = 50013
UNKNOWN_CHANNEL = 10003


class DiscordError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def permanent(self) -> bool:
        """Retrying won't help (no access to the channel, bad request...)."""
        return self.status is not None and 400 <= self.status < 500 and self.status != 429

    def friendly(self) -> str:
        if self.code in (MISSING_ACCESS, MISSING_PERMISSIONS):
            return ("The bot can't post in this class's channel. Give it the View Channel and "
                    "Send Messages permissions there.")
        if self.code == UNKNOWN_CHANNEL:
            return "The class's Discord channel no longer exists. Run /setup in the new channel."
        if self.status == 401:
            return 'The bot token is not valid. Check DISCORD_BOT_TOKEN on the server.'
        return 'Discord did not accept the message. Please try again in a minute.'


def application_id() -> str:
    value = os.getenv('DISCORD_APPLICATION_ID', '')
    if not value:
        raise DiscordError('DISCORD_APPLICATION_ID is not set')
    return value


def _bot_token() -> str:
    token = os.getenv('DISCORD_BOT_TOKEN', '')
    if not token:
        raise DiscordError('DISCORD_BOT_TOKEN is not set', status=401)
    return token


def request(method: str, path: str, payload: Any = None, *, bot: bool = True) -> Any:
    headers = {'User-Agent': USER_AGENT, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    if bot:
        headers['Authorization'] = f'Bot {_bot_token()}'
    body = None if payload is None else json.dumps(payload).encode('utf-8')

    for attempt in range(3):
        req = Request(f'{API_BASE}{path}', data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode('utf-8')
                return json.loads(raw) if raw else None
        except HTTPError as error:
            raw = error.read().decode('utf-8', errors='replace') if error.fp else ''
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {}
            if error.code == 429 and attempt < 2:
                wait = float(data.get('retry_after') or 1)
                if wait <= 10:
                    time.sleep(wait)
                    continue
            if error.code >= 500 and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise DiscordError(f"Discord {method} {path.split('?')[0]} failed: {error.code} {data.get('message', '')}",
                               status=error.code, code=data.get('code')) from error
        except (URLError, TimeoutError, OSError) as error:
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise DiscordError(f'Could not reach Discord: {error}') from error
    raise DiscordError('Discord request failed after retries')


def message_payload(content: str, *, components: list | None = None, ephemeral: bool = False) -> dict:
    payload: dict[str, Any] = {'content': content, 'allowed_mentions': NO_MENTIONS}
    if components:
        payload['components'] = components
    if ephemeral:
        payload['flags'] = EPHEMERAL
    return payload


def link_button(label: str, url: str) -> list[dict]:
    """One action row with one link button."""
    return [{'type': 1, 'components': [{'type': 2, 'style': 5, 'label': label, 'url': url}]}]


# ---------------------------------------------------------------------------
# Channel messages (bot token)
# ---------------------------------------------------------------------------
def post_messages(channel_id: str, messages: list[str]) -> None:
    for content in messages:
        request('POST', f'/channels/{channel_id}/messages', message_payload(content))


# ---------------------------------------------------------------------------
# Interaction responses (interaction token; valid for 15 minutes)
# ---------------------------------------------------------------------------
def edit_original(token: str, content: str, *, components: list | None = None) -> None:
    request('PATCH', f'/webhooks/{application_id()}/{token}/messages/@original',
            message_payload(content, components=components), bot=False)


def followup(token: str, content: str, *, ephemeral: bool) -> None:
    request('POST', f'/webhooks/{application_id()}/{token}', message_payload(content, ephemeral=ephemeral), bot=False)


def reply(token: str, messages: list[str], *, ephemeral: bool, components: list | None = None) -> None:
    """Fill a deferred response: the first part replaces 'thinking…', the rest follow."""
    first, *rest = messages or ['Nothing to show.']
    edit_original(token, first, components=components)
    for part in rest:
        followup(token, part, ephemeral=ephemeral)


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------
def overwrite_commands(commands: list[dict], guild_id: str | None = None) -> list[dict]:
    """Replace the bot's slash commands (globally, or in one server for instant testing)."""
    path = f'/applications/{application_id()}'
    path += f'/guilds/{guild_id}/commands' if guild_id else '/commands'
    return request('PUT', path, commands)
