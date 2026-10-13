"""CR authentication for the dashboard API.

The browser signs in with Supabase Auth and sends its access token as
`Authorization: Bearer <token>`. We validate the token with the Supabase Auth
server and then require the user to be listed in public.cr_members. Both
checks happen on the server for every write, independent of the frontend.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import Header, HTTPException

import db_fetch

AUTH_CACHE_SECONDS = 60
_MAX_CACHE = 256


@dataclass(frozen=True)
class CRUser:
    id: str
    email: str | None


_cache: dict[str, tuple[float, CRUser | None, int]] = {}
_lock = threading.Lock()


def _cached(key: str) -> tuple[CRUser | None, int] | None:
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1], entry[2]
        _cache.pop(key, None)
    return None


def _store(key: str, user: CRUser | None, status: int) -> None:
    with _lock:
        if len(_cache) >= _MAX_CACHE:
            _cache.clear()
        _cache[key] = (time.monotonic() + AUTH_CACHE_SECONDS, user, status)


def clear_auth_cache() -> None:
    with _lock:
        _cache.clear()


def require_cr(authorization: str | None = Header(default=None)) -> CRUser:
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail={'message': 'Please sign in.'})
    token = authorization[7:].strip()
    if not token or len(token) > 4096:
        raise HTTPException(status_code=401, detail={'message': 'Please sign in.'})

    key = hashlib.sha256(token.encode()).hexdigest()
    cached = _cached(key)
    if cached is not None:
        user, status = cached
        if user is None:
            raise HTTPException(status_code=status, detail={'message': _status_message(status)})
        return user

    try:
        auth_user = db_fetch.fetch_auth_user(token)
        if not auth_user or not auth_user.get('id'):
            _store(key, None, 401)
            raise HTTPException(status_code=401, detail={'message': _status_message(401)})
        user_id = str(uuid.UUID(str(auth_user['id'])))
        user = CRUser(user_id, auth_user.get('email'))
        if not db_fetch.is_cr_member(user_id):
            _store(key, None, 403)
            raise HTTPException(status_code=403, detail={'message': _status_message(403)})
    except db_fetch.DatabaseError as error:
        raise HTTPException(status_code=503, detail={'message': 'Could not verify your sign-in right now. Please try again.'}) from error
    except ValueError as error:
        raise HTTPException(status_code=401, detail={'message': _status_message(401)}) from error

    _store(key, user, 200)
    return user


def _status_message(status: int) -> str:
    if status == 403:
        return 'This account is not authorized as a CR. Ask the project owner to add you.'
    return 'Your session has expired. Please sign in again.'
