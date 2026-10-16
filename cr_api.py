"""CR editor API: courses, faculty and exam records of one class, and posting to Discord.

Every route requires a CR editor link (see auth.py) and only sees the class the
link was issued for. Validation here gives
friendly field-level errors; the database functions and triggers enforce the
same rules again, so a bypassed or buggy client still cannot store invalid data.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import date, time as dtime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

import academic
import date_ranges as dr
import db_fetch
import links
import public_api
import updates
from auth import CRSession, clear_auth_cache, require_cr
from Chatbot import formatter
from Chatbot.catalog import catalog_cache
from discord_bot import client as discord

router = APIRouter(prefix='/api', tags=['cr'])
CR = Annotated[CRSession, Depends(require_cr)]

_STATUS_FOR_CODE = {
    'not_found': 404,
    'duplicate': 409,
    'in_use': 409,
    'course_type_locked': 409,
    'unavailable': 503,
}


def _fail(status: int, message: str, field: str | None = None, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={'message': message, 'field': field, **extra})


def _db_error(error: db_fetch.DatabaseError) -> HTTPException:
    if error.code in ('misconfigured', 'database_error', 'bad_response'):
        return _fail(500 if error.code != 'database_error' else 502, 'The database request failed. Nothing was saved.')
    status = _STATUS_FOR_CODE.get(error.code, 422)
    return _fail(status, str(error), code=error.code)


def _data_changed(class_id: int) -> None:
    """Drop cached copies so students (bot and public board) see the change at once."""
    catalog_cache.invalidate(class_id)
    public_api.invalidate()


def _course(user: CRSession, course_id: int) -> dict | None:
    """A course of the CR's class (another class's course is reported as missing)."""
    course = db_fetch.fetch_course(course_id)
    return course if course and course.get('class_id') == user.class_id else None


def _exam(user: CRSession, exam_id: int) -> dict | None:
    row = db_fetch.get_exam(exam_id)
    return row if row and row.get('class_id') == user.class_id else None


def _clean_text(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    value = value.replace('\r\n', '\n').strip()
    if len(value) > max_len:
        raise ValueError(f'must be at most {max_len} characters')
    return value or None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _class_view(info: dict) -> dict:
    return {
        'id': info['id'], 'name': info['name'], 'auto_updates': info['auto_updates'],
        'linked': bool(info.get('discord_channel_id')), 'board_url': links.board_url(info['view_key']),
    }


@router.get('/me')
def me(user: CR) -> dict:
    return {'user_id': user.user_id, 'expires_at': user.expires_at, 'class': _class_view(user.class_info)}


class ClassIn(BaseModel):
    auto_updates: bool


@router.patch('/class')
def update_class(body: ClassIn, user: CR) -> dict:
    try:
        row = db_fetch.update_class(user.class_id, {'auto_updates': body.auto_updates})
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    if row is None:
        raise _fail(404, 'This class no longer exists.')
    clear_auth_cache()
    return {'class': _class_view(row)}


@router.get('/config')
def config(user: CR) -> dict:
    try:
        types = db_fetch.fetch_exam_types()
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    by_type: dict[str, list[str]] = {t: [] for t in academic.COURSE_TYPES}
    for row in types:
        if not row['is_legacy']:
            by_type[row['course_type']].append(row['name'])
    return {
        'exam_types': by_type,
        'legacy_exam_types': [row['name'] for row in types if row['is_legacy']],
        'course_sections': list(academic.COURSE_SECTIONS),
        'timezone': dr.TIMEZONE_NAME,
        'today': dr.today_local().isoformat(),
        'class': _class_view(user.class_info),
    }


# ---------------------------------------------------------------------------
# Faculty
# ---------------------------------------------------------------------------
class FacultyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)

    @field_validator('name')
    @classmethod
    def _strip(cls, v: str) -> str:
        v = ' '.join(v.split())
        if len(v) < 2:
            raise ValueError('Name is required')
        return v


@router.get('/faculty')
def list_faculty(user: CR) -> dict:
    try:
        return {'faculty': db_fetch.fetch_faculty(user.class_id)}
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error


@router.post('/faculty', status_code=201)
def create_faculty(body: FacultyIn, user: CR) -> dict:
    try:
        row = db_fetch.create_faculty(user.class_id, body.name)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, f'"{body.name}" is already in the faculty list.', 'name') from error
        raise _db_error(error) from error
    _data_changed(user.class_id)
    return row


@router.patch('/faculty/{faculty_id}')
def rename_faculty(faculty_id: int, body: FacultyIn, user: CR) -> dict:
    try:
        row = db_fetch.rename_faculty(user.class_id, faculty_id, body.name)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, f'"{body.name}" is already in the faculty list.', 'name') from error
        raise _db_error(error) from error
    _data_changed(user.class_id)
    return row


@router.delete('/faculty/{faculty_id}')
def remove_faculty(faculty_id: int, user: CR) -> dict:
    try:
        outcome = db_fetch.remove_faculty(user.class_id, faculty_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    _data_changed(user.class_id)
    return {'result': outcome}


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------
class CourseIn(BaseModel):
    code: str = Field(max_length=20)
    title: str = Field(max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    faculty_ids: list[int] = Field(default_factory=list, max_length=8)  # Sessional courses
    section_faculty: dict[str, int] = Field(default_factory=dict)       # Theoretical: {'A': id, 'B': id}
    faculty_exception_note: str | None = Field(default=None, max_length=500)  # ignored; kept for old clients

    @field_validator('title')
    @classmethod
    def _title(cls, v: str) -> str:
        v = ' '.join(v.split())
        if len(v) < 2:
            raise ValueError('Course title is required')
        return v

    @field_validator('aliases')
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        cleaned = [' '.join(a.split()) for a in v if a and a.strip()]
        if any(len(a) > 60 for a in cleaned):
            raise ValueError('Each alias must be at most 60 characters')
        return list(dict.fromkeys(cleaned))

    @field_validator('section_faculty')
    @classmethod
    def _sections(cls, v: dict[str, int]) -> dict[str, int]:
        cleaned = {k.strip().upper(): fid for k, fid in v.items() if fid}
        if set(cleaned) - set(academic.COURSE_SECTIONS):
            raise ValueError('Course sections are A and B')
        return dict(sorted(cleaned.items()))


def _validate_course(body: CourseIn) -> tuple[str, list[int], dict[str, int]]:
    """Returns (code, faculty_ids, section_faculty). A Theoretical course's teachers
    are exactly its section teachers (one person may take both sections)."""
    parsed = academic.parse_course_code(body.code)
    if not parsed.ok:
        raise _fail(422, parsed.error, 'code')
    if not academic.has_course_sections(parsed.course_type):
        return parsed.code, sorted(set(body.faculty_ids)), {}
    section_error = academic.section_faculty_error(parsed.course_type, body.section_faculty)
    if section_error:
        raise _fail(422, section_error, 'section_faculty')
    return parsed.code, sorted(set(body.section_faculty.values())), body.section_faculty


@router.get('/courses')
def list_courses(user: CR) -> dict:
    try:
        return {'courses': db_fetch.fetch_active_courses(user.class_id, with_exam_counts=True)}
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error


def _save_course(user: CRSession, course_id: int | None, body: CourseIn) -> dict:
    code, faculty_ids, section_faculty = _validate_course(body)
    try:
        saved_id = db_fetch.save_course(
            class_id=user.class_id, course_id=course_id, code=code, title=body.title, aliases=body.aliases,
            faculty_ids=faculty_ids, section_faculty=section_faculty,
        )
        course = db_fetch.fetch_course(saved_id)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, f'{code} is already configured. Edit the existing course instead.', 'code') from error
        if error.code in ('invalid_course_code',):
            raise _fail(422, str(error), 'code') from error
        if error.code == 'faculty_sections':
            raise _fail(422, str(error), 'section_faculty') from error
        if error.code == 'unknown_faculty':
            raise _fail(422, str(error), 'section_faculty' if section_faculty else 'faculty_ids') from error
        raise _db_error(error) from error
    finally:
        _data_changed(user.class_id)
    return course


@router.post('/courses', status_code=201)
def create_course(body: CourseIn, user: CR) -> dict:
    return _save_course(user, None, body)


@router.patch('/courses/{course_id}')
def update_course(course_id: int, body: CourseIn, user: CR) -> dict:
    return _save_course(user, course_id, body)


@router.delete('/courses/{course_id}')
def remove_course(course_id: int, user: CR) -> dict:
    try:
        outcome = db_fetch.remove_course(user.class_id, course_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    finally:
        _data_changed(user.class_id)
    return {'result': outcome}


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
class ExamIn(BaseModel):
    course_id: int
    exam_type: str = Field(max_length=60)
    exam_date: date
    exam_time: dtime | None = None
    section: str | None = Field(default=None, max_length=10)          # class section (Sessional)
    course_section: str | None = Field(default=None, max_length=10)   # A / B / None = both (Theoretical)
    syllabus: str | None = Field(default=None, max_length=10000)
    venue: str | None = Field(default=None, max_length=200)
    remarks: str | None = Field(default=None, max_length=2000)
    notes_link: str | None = Field(default=None, max_length=1000)
    faculty_ids: list[int] = Field(default_factory=list, max_length=8)
    client_request_id: uuid.UUID | None = None

    @field_validator('syllabus')
    @classmethod
    def _syllabus(cls, v):
        return _clean_text(v, 10000)

    @field_validator('venue')
    @classmethod
    def _venue(cls, v):
        return _clean_text(v, 200)

    @field_validator('remarks')
    @classmethod
    def _remarks(cls, v):
        return _clean_text(v, 2000)

    @field_validator('notes_link')
    @classmethod
    def _link(cls, v):
        v = _clean_text(v, 1000)
        if v and (not v.lower().startswith(('http://', 'https://')) or any(c.isspace() for c in v)):
            raise ValueError('Notes link must be a full URL starting with https://')
        return v

    @field_validator('exam_date')
    @classmethod
    def _date(cls, v: date) -> date:
        if not date(2000, 1, 1) <= v <= date(2100, 12, 31):
            raise ValueError('Exam date is out of range')
        return v


def _theory_exam_section(course: dict, raw: str | None) -> str | None:
    """Validated course section for a Theoretical exam; its teacher(s) must already be assigned."""
    try:
        course_section = academic.normalize_course_section(raw)
    except ValueError as error:
        raise _fail(422, str(error), 'course_section') from error
    assigned = course.get('section_faculty') or {}
    missing = [s for s in ([course_section] if course_section else academic.COURSE_SECTIONS) if s not in assigned]
    if missing:
        raise _fail(422, f'{course["code"]} has no course teacher for Section {" and Section ".join(missing)} yet. '
                         'Assign it under Courses first.', 'course_section')
    return course_section


def _validate_exam(user: CRSession, body: ExamIn, existing: dict | None) -> tuple[dict, str | None, str | None]:
    """Returns (course, class section, course section)."""
    course = _course(user, body.course_id)
    if course is None:
        raise _fail(422, 'Select a course.', 'course_id')
    if course.get('archived_at') and not (existing and existing['course_id'] == body.course_id):
        raise _fail(422, 'That course has been removed from the active course list.', 'course_id')

    types = db_fetch.fetch_exam_types()
    allowed = [t['name'] for t in types if t['course_type'] == course['course_type'] and not t['is_legacy']]
    keeps_legacy_type = (
        existing is not None and existing.get('legacy_exam_id') is not None
        and existing['exam_type'] == body.exam_type and existing['course_id'] == body.course_id
    )
    if body.exam_type not in allowed and not keeps_legacy_type:
        raise _fail(422, f'{body.exam_type} is not valid for a {course["course_type"]} course. '
                         f'Choose one of: {", ".join(allowed)}.', 'exam_type')

    if academic.has_course_sections(course['course_type']):
        # Both course sections sit it at one time; the teachers come from the course section.
        return course, None, _theory_exam_section(course, body.course_section)

    faculty_ids = sorted(set(body.faculty_ids))
    unchanged = existing is not None and existing['course_id'] == body.course_id and \
        sorted(existing.get('exam_faculty_ids') or []) == faculty_ids
    course_faculty = {f['id'] for f in course['faculty']}
    if not unchanged and not set(faculty_ids) <= course_faculty:
        raise _fail(422, 'Selected faculty must be assigned to this course.', 'faculty_ids')

    try:
        section = academic.normalize_section(body.section)
    except ValueError as error:
        raise _fail(422, str(error), 'section') from error
    return course, section, None


def _save_exam(exam_id: int | None, body: ExamIn, user: CRSession) -> dict:
    theory = False
    try:
        existing = _exam(user, exam_id) if exam_id is not None else None
        if exam_id is not None and existing is None:
            raise _fail(404, 'Exam record not found.')
        course, section, course_section = _validate_exam(user, body, existing)
        theory = academic.has_course_sections(course['course_type'])
        saved_id = db_fetch.save_exam(
            class_id=user.class_id, exam_id=exam_id, course_id=body.course_id, exam_type=body.exam_type,
            exam_date=body.exam_date, exam_time=body.exam_time, section=section, course_section=course_section,
            syllabus=body.syllabus, venue=body.venue, remarks=body.remarks, notes_link=body.notes_link,
            faculty_ids=[] if theory else sorted(set(body.faculty_ids)),
            client_request_id=str(body.client_request_id) if body.client_request_id and exam_id is None else None,
            actor=user.user_id,
        )
        public_api.invalidate()
        row = db_fetch.get_exam(saved_id)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            # Theoretical: one record per course section per exam type, whatever the date.
            raise _fail(409, str(error), 'course_section' if theory else 'exam_date') from error
        if error.code == 'invalid_exam_type':
            raise _fail(422, str(error), 'exam_type') from error
        if error.code == 'invalid_faculty':
            raise _fail(422, str(error), 'faculty_ids') from error
        if error.code == 'invalid_course_section':
            raise _fail(422, str(error), 'course_section') from error
        raise _db_error(error) from error
    if row is None:
        raise _fail(502, 'The exam was saved but could not be read back. Refresh to check.')
    return row


@router.get('/exams')
def list_exams(
    user: CR,
    scope: Literal['upcoming', 'past'] = 'upcoming',
    course_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> dict:
    today = dr.today_local()
    query = db_fetch.ExamQuery(
        class_id=user.class_id,
        course_ids=(course_id,) if course_id else None,
        date_from=today if scope == 'upcoming' else None,
        date_to=today - timedelta(days=1) if scope == 'past' else None,
        descending=scope == 'past',
        limit=limit + 1,
        offset=offset,
    )
    try:
        rows = db_fetch.query_exams(query)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    return {'exams': rows[:limit], 'has_more': len(rows) > limit, 'today': today.isoformat()}


@router.get('/exams/{exam_id}')
def get_exam(exam_id: int, user: CR) -> dict:
    try:
        row = _exam(user, exam_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    if row is None:
        raise _fail(404, 'Exam record not found.')
    return row


@router.post('/exams', status_code=201)
def create_exam(body: ExamIn, user: CR) -> dict:
    return _save_exam(None, body, user)


@router.patch('/exams/{exam_id}')
def update_exam(exam_id: int, body: ExamIn, user: CR) -> dict:
    return _save_exam(exam_id, body, user)


@router.delete('/exams/{exam_id}')
def delete_exam(exam_id: int, user: CR) -> dict:
    try:
        deleted = _exam(user, exam_id) is not None and db_fetch.delete_exam(exam_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    finally:
        public_api.invalidate()
    if not deleted:
        raise _fail(404, 'Exam record not found (it may already have been deleted).')
    return {'result': 'deleted'}


@router.post('/exams/preview')
def preview_exam(body: ExamIn, user: CR) -> dict:
    """Exactly what a student would see for this record, using the bot's formatter."""
    try:
        course = _course(user, body.course_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    if course is None:
        raise _fail(422, 'Select a course.', 'course_id')
    section = course_section = None
    section_faculty: list[dict] = []
    if academic.has_course_sections(course['course_type']):
        course_section = _theory_exam_section(course, body.course_section)
        section_faculty = [{'section': s, 'name': f['name']} for s, f in sorted(course['section_faculty'].items())
                           if course_section in (None, s)]
        names = sorted({item['name'] for item in section_faculty}, key=str.lower)
        source = 'course'
    else:
        try:
            section = academic.normalize_section(body.section)
        except ValueError as error:
            raise _fail(422, str(error), 'section') from error
        picked = [f['name'] for f in course['faculty'] if f['id'] in set(body.faculty_ids)]
        names = picked or [f['name'] for f in course['faculty']]
        source = 'exam' if picked else 'course'
    row = {
        'course_code': course['code'], 'course_title': course['title'], 'course_type': course['course_type'],
        'exam_type': body.exam_type, 'exam_date': body.exam_date.isoformat(),
        'exam_time': body.exam_time.isoformat() if body.exam_time else None,
        'section': section, 'course_section': course_section, 'syllabus': body.syllabus, 'venue': body.venue,
        'remarks': body.remarks, 'notes_link': body.notes_link,
        'faculty_names': names, 'faculty_source': source, 'section_faculty': section_faculty,
    }
    return {'text': formatter.format_exam(row, [], today=dr.today_local())}


# ---------------------------------------------------------------------------
# Post to the class's Discord channel
# ---------------------------------------------------------------------------
POST_COOLDOWN_SECONDS = 20
_recent_posts: dict[tuple[int, str], float] = {}
_posts_lock = threading.Lock()


class PostIn(BaseModel):
    kind: Literal['next_exam_day', 'next_exam_notes']  # week updates are posted from Discord


def _post(user: CRSession, what: str, build) -> dict:
    channel = user.class_info.get('discord_channel_id')
    if not channel:
        raise _fail(409, 'This class is not linked to a Discord channel yet. Run /setup in the channel first.')
    key = (user.class_id, what)
    with _posts_lock:
        # A double tap (or two CRs at once) must not post the same update twice.
        if time.monotonic() - _recent_posts.get(key, -1e9) < POST_COOLDOWN_SECONDS:
            raise _fail(429, 'That update was just posted. Wait a few seconds before posting it again.')
        _recent_posts[key] = time.monotonic()
    try:
        update = build()
        discord.post_messages(channel, update.messages)
    except db_fetch.DatabaseError as error:
        _recent_posts.pop(key, None)
        raise _db_error(error) from error
    except discord.DiscordError as error:
        _recent_posts.pop(key, None)
        raise _fail(502, error.friendly()) from error
    return {'posted': len(update.messages), 'exam_count': update.exam_count}


@router.post('/discord/post')
def post_update(body: PostIn, user: CR) -> dict:
    now = dr.now_local()
    builders = {
        'next_exam_day': lambda: updates.next_exam_day_update(user.class_id, now),
        'next_exam_notes': lambda: updates.next_exam_day_update(user.class_id, now, notes_only=True),
    }
    return _post(user, body.kind, builders[body.kind])


@router.post('/discord/post/exams/{exam_id}')
def post_exam(exam_id: int, user: CR) -> dict:
    try:
        row = _exam(user, exam_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    if row is None:
        raise _fail(404, 'Exam record not found.')
    return _post(user, f'exam:{exam_id}', lambda: updates.exam_update(row, dr.now_local()))
