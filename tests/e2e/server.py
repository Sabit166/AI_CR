"""Backend for UI end-to-end tests: the real FastAPI app against the isolated
Docker database (tests/db). Two classes are created at start-up, as if /setup
had been run in two Discord channels; the browser gets their links from the
test-only GET /e2e/links. Posting to Discord is captured instead of sent
(GET /e2e/posts).

    python tests/e2e/server.py      # listens on 127.0.0.1:8011
"""
import base64
import hashlib
import hmac
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SECRET = b'aicr-local-test-jwt-secret-0123456789abcdef'
APP = 'http://127.0.0.1:4179'


def _jwt(role: str) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    header = b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
    payload = b64(json.dumps({'role': role, 'exp': 4102444800}).encode())
    return f'{header}.{payload}.' + b64(hmac.new(SECRET, f'{header}.{payload}'.encode(), hashlib.sha256).digest())


os.environ.update({
    'SUPABASE_URL': 'http://localhost:54321',
    'SUPABASE_API_KEY': _jwt('service_role'),
    'OPENAI_API_KEY': '', 'MODEL': '',
    'DISCORD_BOT_TOKEN': '', 'SCHEDULER_ENABLED': '0',
    'EDITOR_LINK_SECRET': 'e2e-editor-link-secret-0123456789abcdef',
    'SITE_URL': APP,
    'CORS_ALLOW_ORIGINS': APP,
})

import uvicorn  # noqa: E402

import db_fetch  # noqa: E402
import links  # noqa: E402
import main  # noqa: E402
from discord_bot import client as discord  # noqa: E402

POSTS: list[dict] = []
discord.post_messages = lambda channel, messages: POSTS.append({'channel': channel, 'messages': messages})


def _class(name: str) -> dict:
    snowflake = lambda: str(random.randint(10 ** 17, 10 ** 18 - 1))  # noqa: E731
    return db_fetch.create_class(name=name, guild_id=snowflake(), channel_id=snowflake(), cr_role_id=None)


CLASSES = {}


@main.app.get('/e2e/links')
def e2e_links() -> dict:
    if not CLASSES:
        CLASSES['mine'] = _class('E2E Class A')
        CLASSES['other'] = _class('E2E Class B')
    return {
        name: {
            'editor': links.editor_url(links.make_editor_token(cls['id'], '123456789012345678')),
            'board': links.board_url(cls['view_key']),
            'channel': cls['discord_channel_id'],
        }
        for name, cls in CLASSES.items()
    }


@main.app.get('/e2e/posts')
def e2e_posts() -> list[dict]:
    return POSTS


if __name__ == '__main__':
    uvicorn.run(main.app, host='127.0.0.1', port=8011, log_level='warning')
