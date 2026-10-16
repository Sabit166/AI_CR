"""Links the Discord bot hands out instead of accounts.

* Board link (read-only, anyone in the channel): SITE_URL/c/<view_key>. The key
  is a random uuid stored on the class; it never changes on its own.
* Editor link (CRs only, sent privately by /manage): SITE_URL/cr/#t=<token>.
  The token is signed with EDITOR_LINK_SECRET and names the class, the Discord
  user and an expiry; nothing about it is stored. It travels in the URL
  fragment, which browsers never send to a server or put in a Referer.
  Changing EDITOR_LINK_SECRET revokes every editor link at once.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

TOKEN_VERSION = 'e1'
DEFAULT_TTL_HOURS = 12


class LinksMisconfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class EditorClaims:
    class_id: int
    user_id: str      # Discord user id
    expires_at: int   # unix seconds


def _secret() -> bytes:
    secret = os.getenv('EDITOR_LINK_SECRET', '')
    if len(secret) < 32:
        raise LinksMisconfigured('EDITOR_LINK_SECRET must be set (at least 32 characters)')
    return secret.encode()


def _sign(payload: str) -> str:
    digest = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode()


def ttl_hours() -> float:
    try:
        return max(0.25, min(float(os.getenv('EDITOR_LINK_HOURS', DEFAULT_TTL_HOURS)), 24 * 7))
    except ValueError:
        return DEFAULT_TTL_HOURS


def make_editor_token(class_id: int, user_id: str, *, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + ttl_hours() * 3600)
    payload = f'{TOKEN_VERSION}.{int(class_id)}.{user_id}.{expires}'
    return f'{payload}.{_sign(payload)}'


def read_editor_token(token: str, *, now: float | None = None) -> EditorClaims | None:
    """The claims of a valid, unexpired token; None otherwise (never raises for bad input)."""
    if not token or len(token) > 300:
        return None
    parts = token.split('.')
    if len(parts) != 5 or parts[0] != TOKEN_VERSION:
        return None
    payload, signature = '.'.join(parts[:4]), parts[4]
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    _, class_id, user_id, expires = parts[:4]
    if not (class_id.isdigit() and user_id.isdigit() and expires.isdigit()):
        return None
    if int(expires) < (now if now is not None else time.time()):
        return None
    return EditorClaims(int(class_id), user_id, int(expires))


def site_url() -> str:
    return os.getenv('SITE_URL', 'http://localhost:5173').rstrip('/')


def board_url(view_key: str) -> str:
    return f'{site_url()}/c/{view_key}'


def editor_url(token: str) -> str:
    return f'{site_url()}/cr/#t={token}'
