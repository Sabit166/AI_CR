"""Supabase (PostgREST) access for the backend.

Only server-side code imports this module; it uses the Supabase *secret* key,
which must never reach the browser. Every function maps to one fixed,
parameterized PostgREST request or RPC — nothing here accepts SQL or arbitrary
column names from callers.
"""
from __future__ import annotations

import contextvars
import json
import os
import time
from dataclasses import dataclass, field
from datetime import date, time as dtime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

TIMEOUT_SECONDS = 15


def _load_env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value

    env_path = Path(__file__).with_name('.env')
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, raw_value = line.split('=', 1)
        if key.strip() == name:
            return raw_value.strip().strip('"').strip("'")

    return None


# ---------------------------------------------------------------------------
# Errors and metrics
# ---------------------------------------------------------------------------
class DatabaseError(RuntimeError):
    """Supabase could not be reached or rejected the request.

    `code` is the AICR error code raised by our SQL functions (e.g. 'duplicate',
    'faculty_count'), or a generic code such as 'unavailable'.
    """

    def __init__(self, message: str, *, code: str = 'database_error', status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class CallMetrics:
    db_calls: int = 0
    db_ms: float = 0.0
    llm_calls: int = 0
    llm_ms: float = 0.0
    notes: list[str] = field(default_factory=list)


_metrics: contextvars.ContextVar[CallMetrics | None] = contextvars.ContextVar('aicr_metrics', default=None)


def start_metrics() -> CallMetrics:
    metrics = CallMetrics()
    _metrics.set(metrics)
    return metrics


def current_metrics() -> CallMetrics | None:
    return _metrics.get()


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------
def _config() -> tuple[str, str]:
    supabase_url = _load_env_value('SUPABASE_URL')
    supabase_api_key = _load_env_value('SUPABASE_API_KEY')
    if not supabase_url or not supabase_api_key:
        raise DatabaseError('SUPABASE_URL and SUPABASE_API_KEY must be set', code='misconfigured')
    return supabase_url.rstrip('/'), supabase_api_key


def rest_base_url() -> str:
    """SUPABASE_URL is the PostgREST root (https://<ref>.supabase.co/rest/v1)."""
    return _config()[0]


def auth_base_url() -> str:
    base = rest_base_url()
    if base.endswith('/rest/v1'):
        base = base[: -len('/rest/v1')]
    return f'{base}/auth/v1'


def _parse_error_body(body: str) -> tuple[str, str]:
    """Return (code, message). Our SQL functions raise 'AICR:<code>:<message>'."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return 'database_error', 'Unexpected database error'
    message = str(parsed.get('message') or parsed.get('msg') or parsed.get('error_description') or '')
    if message.startswith('AICR:'):
        _, code, text = message.split(':', 2)
        return code, text
    pg_code = parsed.get('code')
    if pg_code == '23505':
        return 'duplicate', 'A record with the same key already exists.'
    if pg_code == '23503':
        return 'in_use', 'This record is still referenced by other data.'
    if pg_code in ('23514', '22023', '22P02', '22007', '22008'):
        return 'invalid', 'The database rejected one of the values.'
    return 'database_error', 'Unexpected database error'


def _http(method: str, url: str, *, headers: dict[str, str], payload: Any = None) -> Any:
    body = None if payload is None else json.dumps(payload, default=_json_default).encode('utf-8')
    request = Request(url, data=body, headers=headers, method=method)
    started = time.perf_counter()
    metrics = current_metrics()
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode('utf-8')
    except HTTPError as error:
        raw_error = error.read().decode('utf-8', errors='replace') if error.fp else ''
        code, message = _parse_error_body(raw_error)
        raise DatabaseError(message, code=code, status=error.code) from error
    except (URLError, TimeoutError, OSError) as error:
        raise DatabaseError('Could not reach the database. Please try again shortly.', code='unavailable') from error
    finally:
        if metrics is not None:
            metrics.db_calls += 1
            metrics.db_ms += (time.perf_counter() - started) * 1000

    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise DatabaseError('Unexpected response format from Supabase', code='bad_response') from error


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, dtime)):
        return value.isoformat()
    raise TypeError(f'Cannot serialize {type(value).__name__}')


def _rest(
    method: str,
    path: str,
    params: list[tuple[str, str]] | None = None,
    payload: Any = None,
    prefer: str | None = None,
) -> Any:
    base, key = _config()
    query = f'?{urlencode(params, quote_via=quote, safe=",*().:")}' if params else ''
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    if prefer:
        headers['Prefer'] = prefer
    return _http(method, f'{base}/{path.lstrip("/")}{query}', headers=headers, payload=payload)


def rpc(name: str, args: dict[str, Any]) -> Any:
    return _rest('POST', f'rpc/{name}', payload=args)


# ---------------------------------------------------------------------------
# Catalog (courses, faculty, exam types)
# ---------------------------------------------------------------------------
COURSE_SELECT = (
    'id,class_id,code,title,course_type,aliases,faculty_exception_note,archived_at,'
    'course_faculty(sections,faculty(id,name))'
)


def fetch_exam_types() -> list[dict]:
    return _rest('GET', 'exam_types', [('select', 'name,course_type,sort_order,is_legacy'), ('order', 'sort_order.asc')]) or []


def fetch_active_courses(class_id: int, with_exam_counts: bool = False) -> list[dict]:
    select = COURSE_SELECT + (',exams(count)' if with_exam_counts else '')
    rows = _rest('GET', 'courses', [
        ('select', select), ('class_id', f'eq.{int(class_id)}'), ('archived_at', 'is.null'), ('order', 'code.asc'),
    ]) or []
    return [_flatten_course(row) for row in rows]


def fetch_course(course_id: int) -> dict | None:
    rows = _rest('GET', 'courses', [('select', COURSE_SELECT), ('id', f'eq.{int(course_id)}')]) or []
    return _flatten_course(rows[0]) if rows else None


def _flatten_course(row: dict) -> dict:
    links = [link for link in row.pop('course_faculty', []) or [] if link.get('faculty')]
    row['faculty'] = sorted((link['faculty'] for link in links), key=lambda f: f['name'].lower())
    # Theoretical courses: {'A': {id, name}, 'B': {id, name}} (one teacher may hold both); else {}.
    row['section_faculty'] = {
        section: link['faculty'] for link in links for section in sorted(link.get('sections') or ())
    }
    if 'exams' in row:
        exams = row.pop('exams') or [{'count': 0}]
        row['exam_count'] = exams[0].get('count', 0)
    return row


def fetch_faculty(class_id: int, include_archived: bool = False) -> list[dict]:
    params = [('select', 'id,name,archived_at'), ('class_id', f'eq.{int(class_id)}'), ('order', 'name.asc')]
    if not include_archived:
        params.append(('archived_at', 'is.null'))
    return _rest('GET', 'faculty', params) or []


# ---------------------------------------------------------------------------
# Faculty / course writes (CR only — callers must enforce authorization).
# Every write names its class; the RPCs refuse rows of another class.
# ---------------------------------------------------------------------------
def create_faculty(class_id: int, name: str) -> dict:
    rows = _rest('POST', 'faculty', [('select', 'id,name,archived_at')], {'class_id': int(class_id), 'name': name},
                 prefer='return=representation')
    return rows[0]


def rename_faculty(class_id: int, faculty_id: int, name: str) -> dict:
    rows = _rest(
        'PATCH', 'faculty',
        [('id', f'eq.{int(faculty_id)}'), ('class_id', f'eq.{int(class_id)}'), ('archived_at', 'is.null'),
         ('select', 'id,name,archived_at')],
        {'name': name}, prefer='return=representation',
    ) or []
    if not rows:
        raise DatabaseError('Faculty member not found.', code='not_found', status=404)
    return rows[0]


def remove_faculty(class_id: int, faculty_id: int) -> str:
    return rpc('cr_remove_faculty', {'p_class_id': int(class_id), 'p_faculty_id': int(faculty_id)})


def save_course(
    *,
    class_id: int,
    course_id: int | None,
    code: str,
    title: str,
    aliases: list[str],
    faculty_ids: list[int],
    section_faculty: dict[str, int],
) -> int:
    return rpc('cr_save_course', {
        'p_class_id': class_id,
        'p_course_id': course_id,
        'p_code': code,
        'p_title': title,
        'p_aliases': aliases,
        'p_faculty_ids': faculty_ids,
        'p_section_faculty': section_faculty,
    })


def remove_course(class_id: int, course_id: int) -> str:
    return rpc('cr_remove_course', {'p_class_id': int(class_id), 'p_course_id': int(course_id)})


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
EXAM_DETAIL_FIELDS = (
    'id', 'course_id', 'course_code', 'course_title', 'course_type', 'course_archived',
    'exam_type', 'exam_date', 'exam_time', 'section', 'syllabus', 'venue', 'remarks',
    'notes_link', 'faculty_ids', 'faculty_names', 'faculty_source', 'exam_faculty_ids',
    'legacy_exam_id', 'created_at', 'updated_at', 'course_section', 'section_faculty', 'class_id',
)


@dataclass
class ExamQuery:
    """A fully parameterized read of public.exam_details. Values are validated
    before they get here; only whitelisted columns can be selected."""

    select: tuple[str, ...] = EXAM_DETAIL_FIELDS
    class_id: int | None = None          # the class (channel) whose exams to read
    course_ids: tuple[int, ...] | None = None
    exam_types: tuple[str, ...] | None = None
    faculty_ids: tuple[int, ...] | None = None
    section: str | None = None           # class/course section: matches it OR whole-class/both-sections (NULL) rows
    date_from: date | None = None        # inclusive
    date_to: date | None = None          # inclusive
    descending: bool = False
    limit: int = 50
    offset: int = 0


def build_exam_query_params(query: ExamQuery) -> list[tuple[str, str]]:
    unknown = set(query.select) - set(EXAM_DETAIL_FIELDS)
    if unknown:
        raise ValueError(f'Unknown exam_details fields: {sorted(unknown)}')

    params: list[tuple[str, str]] = [('select', ','.join(query.select))]
    if query.class_id is not None:
        params.append(('class_id', f'eq.{int(query.class_id)}'))
    if query.course_ids is not None:
        params.append(('course_id', f'in.({",".join(str(int(i)) for i in query.course_ids)})'))
    if query.exam_types is not None:
        params.append(('exam_type', f'in.({",".join(_quote_value(t) for t in query.exam_types)})'))
    if query.faculty_ids is not None:
        params.append(('faculty_ids', f'ov.{{{",".join(str(int(i)) for i in query.faculty_ids)}}}'))
    if query.section is not None:
        value = _quote_value(query.section)
        params.append(('and', f'(or(section.is.null,section.eq.{value}),'
                              f'or(course_section.is.null,course_section.eq.{value}))'))
    if query.date_from is not None:
        params.append(('exam_date', f'gte.{query.date_from.isoformat()}'))
    if query.date_to is not None:
        params.append(('exam_date', f'lte.{query.date_to.isoformat()}'))
    direction = 'desc' if query.descending else 'asc'
    params.append(('order', f'exam_date.{direction},exam_time.{direction}.nullsfirst,course_code.asc,id.asc'))
    params.append(('limit', str(int(query.limit))))
    if query.offset:
        params.append(('offset', str(int(query.offset))))
    return params


def _quote_value(value: str) -> str:
    """PostgREST list/logic value quoting: wrap in double quotes, escape \\ and \"."""
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def query_exams(query: ExamQuery) -> list[dict]:
    rows = _rest('GET', 'exam_details', build_exam_query_params(query))
    if not isinstance(rows, list):
        raise DatabaseError('Unexpected response format from Supabase', code='bad_response')
    return rows


def get_exam(exam_id: int) -> dict | None:
    rows = _rest('GET', 'exam_details', [('select', ','.join(EXAM_DETAIL_FIELDS)), ('id', f'eq.{int(exam_id)}')]) or []
    return rows[0] if rows else None


def save_exam(
    *,
    class_id: int,
    exam_id: int | None,
    course_id: int,
    exam_type: str,
    exam_date: date,
    exam_time: dtime | None,
    section: str | None,
    course_section: str | None,
    syllabus: str | None,
    venue: str | None,
    remarks: str | None,
    notes_link: str | None,
    faculty_ids: list[int],
    client_request_id: str | None,
    actor: str | None,
) -> int:
    return rpc('cr_save_exam', {
        'p_class_id': class_id,
        'p_exam_id': exam_id,
        'p_course_id': course_id,
        'p_exam_type': exam_type,
        'p_exam_date': exam_date,
        'p_exam_time': exam_time,
        'p_section': section,
        'p_course_section': course_section,
        'p_syllabus': syllabus,
        'p_venue': venue,
        'p_remarks': remarks,
        'p_notes_link': notes_link,
        'p_faculty_ids': faculty_ids,
        'p_client_request_id': client_request_id,
        'p_actor': actor,
    })


def delete_exam(exam_id: int) -> bool:
    rows = _rest('DELETE', 'exams', [('id', f'eq.{int(exam_id)}'), ('select', 'id')], prefer='return=representation') or []
    return bool(rows)


# ---------------------------------------------------------------------------
# Classes (one per Discord channel) and automatic-post bookkeeping
# ---------------------------------------------------------------------------
CLASS_FIELDS = 'id,name,discord_guild_id,discord_channel_id,cr_role_id,view_key,auto_updates,archived_at'


def _one_class(params: list[tuple[str, str]]) -> dict | None:
    rows = _rest('GET', 'classes', [('select', CLASS_FIELDS), ('archived_at', 'is.null'), *params]) or []
    return rows[0] if rows else None


def fetch_class(class_id: int) -> dict | None:
    return _one_class([('id', f'eq.{int(class_id)}')])


def fetch_class_by_channel(channel_id: str) -> dict | None:
    return _one_class([('discord_channel_id', f'eq.{snowflake(channel_id)}')])


def fetch_class_by_view_key(view_key: str) -> dict | None:
    return _one_class([('view_key', f'eq.{view_key}')])


def fetch_scheduled_classes() -> list[dict]:
    """Active classes linked to a channel with automatic updates on."""
    return _rest('GET', 'classes', [
        ('select', CLASS_FIELDS), ('archived_at', 'is.null'), ('discord_channel_id', 'not.is.null'),
        ('auto_updates', 'is.true'), ('order', 'id.asc'),
    ]) or []


def fetch_unlinked_classes() -> list[dict]:
    """Classes without a channel (the Discord migration put the earlier data in one)."""
    return _rest('GET', 'classes', [
        ('select', CLASS_FIELDS), ('archived_at', 'is.null'), ('discord_channel_id', 'is.null'), ('order', 'id.asc'),
    ]) or []


def create_class(*, name: str, guild_id: str, channel_id: str, cr_role_id: str | None) -> dict:
    rows = _rest('POST', 'classes', [('select', CLASS_FIELDS)], {
        'name': name, 'discord_guild_id': snowflake(guild_id), 'discord_channel_id': snowflake(channel_id),
        'cr_role_id': snowflake(cr_role_id) if cr_role_id else None,
    }, prefer='return=representation')
    return rows[0]


CLASS_UPDATABLE = frozenset({'name', 'discord_guild_id', 'discord_channel_id', 'cr_role_id', 'auto_updates'})


def update_class(class_id: int, changes: dict, *, only_if_unlinked: bool = False) -> dict | None:
    if set(changes) - CLASS_UPDATABLE:
        raise ValueError(f'Unknown class fields: {sorted(set(changes) - CLASS_UPDATABLE)}')
    params = [('id', f'eq.{int(class_id)}'), ('archived_at', 'is.null'), ('select', CLASS_FIELDS)]
    if only_if_unlinked:
        params.append(('discord_channel_id', 'is.null'))
    rows = _rest('PATCH', 'classes', params, changes, prefer='return=representation') or []
    return rows[0] if rows else None


def claim_notification(class_id: int, key: str) -> bool:
    """True if this call claimed `key` for the class, False if it was already claimed."""
    rows = _rest('POST', 'class_notifications', [('on_conflict', 'class_id,key'), ('select', 'key')],
                 {'class_id': int(class_id), 'key': key},
                 prefer='resolution=ignore-duplicates,return=representation') or []
    return bool(rows)


def finish_notification(class_id: int, key: str, status: str, detail: str | None = None) -> None:
    _rest('PATCH', 'class_notifications', [('class_id', f'eq.{int(class_id)}'), ('key', f'eq.{key}')],
          {'status': status, 'detail': (detail or '')[:500] or None})


def release_notification(class_id: int, key: str) -> None:
    """Undo a claim after a temporary failure so the next run retries it."""
    _rest('DELETE', 'class_notifications', [('class_id', f'eq.{int(class_id)}'), ('key', f'eq.{key}')])


def snowflake(value: str | int) -> str:
    """A Discord id as text (they exceed JavaScript's safe integer range)."""
    text = str(value).strip()
    if not text.isdigit() or not 5 <= len(text) <= 25:
        raise ValueError('not a Discord id')
    return text
