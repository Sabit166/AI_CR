"""Read-only exam board for students: no sign-in, no writes.

Serves the same information the Messenger bot already answers publicly, minus
internal bookkeeping (who saved a record, legacy ids, faculty ids). Responses
are cached briefly so a whole class opening the page at once costs the
database a handful of queries; CR writes clear the cache (see cr_api.py).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

import date_ranges as dr
import db_fetch
from Chatbot.catalog import catalog_cache

router = APIRouter(prefix='/api/public', tags=['public'])

PUBLIC_CACHE_SECONDS = float(os.getenv('PUBLIC_CACHE_SECONDS', '30'))
PUBLIC_EXAM_FIELDS = (
    'id', 'course_id', 'course_code', 'course_title', 'course_type', 'exam_type', 'exam_date',
    'exam_time', 'section', 'syllabus', 'venue', 'remarks', 'notes_link', 'faculty_names',
)

_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_MAX_CACHE_ENTRIES = 256


def invalidate() -> None:
    with _cache_lock:
        _cache.clear()


def _cached(key: tuple, build) -> dict:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _cache_lock:
        if len(_cache) >= _MAX_CACHE_ENTRIES:
            _cache.clear()
        _cache[key] = (now + PUBLIC_CACHE_SECONDS, value)
    return value


def _unavailable(error: db_fetch.DatabaseError) -> HTTPException:
    return HTTPException(status_code=503, detail={'message': 'Exam updates are temporarily unavailable. Try again in a minute.'})


def _cache_headers(response: Response) -> None:
    response.headers['Cache-Control'] = f'public, max-age={int(PUBLIC_CACHE_SECONDS)}'


@router.get('/courses')
def public_courses(response: Response) -> dict:
    try:
        catalog = catalog_cache.get()
    except db_fetch.DatabaseError as error:
        raise _unavailable(error) from error
    _cache_headers(response)
    return {'courses': [
        {'id': c.id, 'code': c.code, 'title': c.title, 'course_type': c.course_type}
        for c in sorted(catalog.courses, key=lambda c: c.code)
    ]}


@router.get('/exams')
def public_exams(
    response: Response,
    scope: Literal['upcoming', 'past'] = 'upcoming',
    course_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=2000),
) -> dict:
    today = dr.today_local()

    def build() -> dict:
        query = db_fetch.ExamQuery(
            select=PUBLIC_EXAM_FIELDS,
            course_ids=(course_id,) if course_id else None,
            date_from=today if scope == 'upcoming' else None,
            date_to=today - timedelta(days=1) if scope == 'past' else None,
            descending=scope == 'past',
            limit=limit + 1,
            offset=offset,
        )
        rows = db_fetch.query_exams(query)
        return {'exams': rows[:limit], 'has_more': len(rows) > limit, 'today': today.isoformat()}

    try:
        result = _cached((today, scope, course_id, limit, offset), build)
    except db_fetch.DatabaseError as error:
        raise _unavailable(error) from error
    _cache_headers(response)
    return result
