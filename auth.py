"""CR authorization for the editor API.

There are no accounts. A CR runs /manage in their class's Discord channel; the
bot checks they are a CR there and sends them, privately, a signed editor link
for that class (links.py). The browser sends the token as
`Authorization: Bearer <token>`, and every editor route is scoped to the class
named in it, so a link for one class can never read or change another.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException

import db_fetch
import links

CLASS_CACHE_SECONDS = 30


@dataclass(frozen=True)
class CRSession:
    class_id: int
    user_id: str          # Discord user id of the CR the link was issued to
    class_info: dict
    expires_at: int


_class_cache: dict[int, tuple[float, dict | None]] = {}
_lock = threading.Lock()


def _class(class_id: int) -> dict | None:
    with _lock:
        hit = _class_cache.get(class_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    row = db_fetch.fetch_class(class_id)
    with _lock:
        if len(_class_cache) > 256:
            _class_cache.clear()
        _class_cache[class_id] = (time.monotonic() + CLASS_CACHE_SECONDS, row)
    return row


def clear_auth_cache() -> None:
    with _lock:
        _class_cache.clear()


EXPIRED = 'This editor link has expired or is not valid. Run /manage in your class channel on Discord for a new one.'


def require_cr(authorization: str | None = Header(default=None)) -> CRSession:
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail={'message': EXPIRED})
    try:
        claims = links.read_editor_token(authorization[7:].strip())
    except links.LinksMisconfigured as error:
        raise HTTPException(status_code=503, detail={'message': 'Editor links are not configured on the server.'}) from error
    if claims is None:
        raise HTTPException(status_code=401, detail={'message': EXPIRED})
    try:
        info = _class(claims.class_id)
    except db_fetch.DatabaseError as error:
        raise HTTPException(status_code=503, detail={'message': 'Could not check your link right now. Please try again.'}) from error
    if info is None:
        raise HTTPException(status_code=403, detail={'message': 'This class no longer exists.'})
    return CRSession(claims.class_id, claims.user_id, info, claims.expires_at)
