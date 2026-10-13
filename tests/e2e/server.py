"""Backend for UI end-to-end tests: the real FastAPI app against the isolated
Docker database (tests/db). Only the Supabase Auth check is stubbed so the
browser can use a fake session; CR authorization still runs through the same
dependency.

    python tests/e2e/server.py      # listens on 127.0.0.1:8011
"""
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SECRET = b'aicr-local-test-jwt-secret-0123456789abcdef'


def _jwt(role: str) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    header = b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
    payload = b64(json.dumps({'role': role, 'exp': 4102444800}).encode())
    return f'{header}.{payload}.' + b64(hmac.new(SECRET, f'{header}.{payload}'.encode(), hashlib.sha256).digest())


os.environ.update({
    'SUPABASE_URL': 'http://localhost:54321',
    'SUPABASE_API_KEY': _jwt('service_role'),
    'OPENAI_API_KEY': '', 'MODEL': '', 'PAGE_ACCESS_TOKEN': 'unused',
    'CORS_ALLOW_ORIGINS': 'http://127.0.0.1:4179',
})

import uvicorn  # noqa: E402

import db_fetch  # noqa: E402
import main  # noqa: E402

USERS = {
    'cr@e2e.test': {'id': '44444444-4444-4444-4444-444444444444', 'email': 'cr@e2e.test'},
    'student@e2e.test': {'id': '55555555-5555-5555-5555-555555555555', 'email': 'student@e2e.test'},
}


def fake_auth_user(token: str):
    """The browser's fake session token is an unsigned JWT whose payload names the user."""
    try:
        payload = token.split('.')[1]
        email = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))['email']
    except (IndexError, ValueError, KeyError):
        return None
    return USERS.get(email)


db_fetch.fetch_auth_user = fake_auth_user
db_fetch.is_cr_member = lambda user_id: user_id == USERS['cr@e2e.test']['id']

if __name__ == '__main__':
    uvicorn.run(main.app, host='127.0.0.1', port=8011, log_level='warning')
