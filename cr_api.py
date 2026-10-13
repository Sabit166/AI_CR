"""CR dashboard API: courses, faculty and exam records.

Every route requires an authenticated CR (see auth.py). Validation here gives
friendly field-level errors; the database functions and triggers enforce the
same rules again, so a bypassed or buggy client still cannot store invalid data.
"""
from __future__ import annotations

import uuid
from datetime import date, time as dtime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

import academic
import date_ranges as dr
import db_fetch
import public_api
from auth import CRUser, require_cr
from Chatbot import formatter
from Chatbot.catalog import catalog_cache

router = APIRouter(prefix='/api', tags=['cr'])
CR = Annotated[CRUser, Depends(require_cr)]

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


def _data_changed() -> None:
    """Drop cached copies so students (bot and public board) see the change at once."""
    catalog_cache.invalidate()
    public_api.invalidate()


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
@router.get('/me')
def me(user: CR) -> dict:
    return {'id': user.id, 'email': user.email}


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
        'faculty_rules': {k: {'min': v[0], 'max': v[1]} for k, v in academic.FACULTY_COUNT_RULES.items()},
        'timezone': dr.TIMEZONE_NAME,
        'today': dr.today_local().isoformat(),
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
        return {'faculty': db_fetch.fetch_faculty()}
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error


@router.post('/faculty', status_code=201)
def create_faculty(body: FacultyIn, user: CR) -> dict:
    try:
        row = db_fetch.create_faculty(body.name)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, f'"{body.name}" is already in the faculty list.', 'name') from error
        raise _db_error(error) from error
    _data_changed()
    return row


@router.patch('/faculty/{faculty_id}')
def rename_faculty(faculty_id: int, body: FacultyIn, user: CR) -> dict:
    try:
        row = db_fetch.rename_faculty(faculty_id, body.name)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, f'"{body.name}" is already in the faculty list.', 'name') from error
        raise _db_error(error) from error
    _data_changed()
    return row


@router.delete('/faculty/{faculty_id}')
def remove_faculty(faculty_id: int, user: CR) -> dict:
    try:
        outcome = db_fetch.remove_faculty(faculty_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    _data_changed()
    return {'result': outcome}


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------
class CourseIn(BaseModel):
    code: str = Field(max_length=20)
    title: str = Field(max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    faculty_ids: list[int] = Field(default_factory=list, max_length=8)
    faculty_exception_note: str | None = Field(default=None, max_length=500)

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


def _validate_course(body: CourseIn) -> tuple[str, str]:
    parsed = academic.parse_course_code(body.code)
    if not parsed.ok:
        raise _fail(422, parsed.error, 'code')
    count_error = academic.faculty_count_error(parsed.course_type, len(set(body.faculty_ids)))
    note = (body.faculty_exception_note or '').strip()
    if count_error and len(note) < 3:
        raise _fail(422, f'{count_error} Select the usual number, or add a short exception note explaining why.',
                    'faculty_ids', can_override=True)
    return parsed.code, parsed.course_type


@router.get('/courses')
def list_courses(user: CR) -> dict:
    try:
        return {'courses': db_fetch.fetch_active_courses(with_exam_counts=True)}
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error


def _save_course(course_id: int | None, body: CourseIn) -> dict:
    code, _ = _validate_course(body)
    note = (body.faculty_exception_note or '').strip() or None
    if not academic.faculty_count_error(academic.course_type_for_code(code), len(set(body.faculty_ids))):
        note = None  # the exception note only applies when the count is unusual
    try:
        saved_id = db_fetch.save_course(
            course_id=course_id, code=code, title=body.title, aliases=body.aliases,
            faculty_ids=sorted(set(body.faculty_ids)), faculty_exception_note=note,
        )
        course = db_fetch.fetch_course(saved_id)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, f'{code} is already configured. Edit the existing course instead.', 'code') from error
        if error.code in ('invalid_course_code',):
            raise _fail(422, str(error), 'code') from error
        if error.code in ('faculty_count', 'unknown_faculty'):
            raise _fail(422, str(error), 'faculty_ids') from error
        raise _db_error(error) from error
    finally:
        _data_changed()
    return course


@router.post('/courses', status_code=201)
def create_course(body: CourseIn, user: CR) -> dict:
    return _save_course(None, body)


@router.patch('/courses/{course_id}')
def update_course(course_id: int, body: CourseIn, user: CR) -> dict:
    return _save_course(course_id, body)


@router.delete('/courses/{course_id}')
def remove_course(course_id: int, user: CR) -> dict:
    try:
        outcome = db_fetch.remove_course(course_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    finally:
        _data_changed()
    return {'result': outcome}


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
class ExamIn(BaseModel):
    course_id: int
    exam_type: str = Field(max_length=60)
    exam_date: date
    exam_time: dtime | None = None
    section: str | None = Field(default=None, max_length=10)
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


def _validate_exam(body: ExamIn, existing: dict | None) -> tuple[dict, str | None]:
    course = db_fetch.fetch_course(body.course_id)
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
    return course, section


def _save_exam(exam_id: int | None, body: ExamIn, user: CRUser) -> dict:
    try:
        existing = db_fetch.get_exam(exam_id) if exam_id is not None else None
        if exam_id is not None and existing is None:
            raise _fail(404, 'Exam record not found.')
        _, section = _validate_exam(body, existing)
        saved_id = db_fetch.save_exam(
            exam_id=exam_id, course_id=body.course_id, exam_type=body.exam_type,
            exam_date=body.exam_date, exam_time=body.exam_time, section=section,
            syllabus=body.syllabus, venue=body.venue, remarks=body.remarks, notes_link=body.notes_link,
            faculty_ids=sorted(set(body.faculty_ids)),
            client_request_id=str(body.client_request_id) if body.client_request_id and exam_id is None else None,
            user_id=user.id,
        )
        public_api.invalidate()
        row = db_fetch.get_exam(saved_id)
    except db_fetch.DatabaseError as error:
        if error.code == 'duplicate':
            raise _fail(409, str(error), 'exam_date') from error
        if error.code == 'invalid_exam_type':
            raise _fail(422, str(error), 'exam_type') from error
        if error.code == 'invalid_faculty':
            raise _fail(422, str(error), 'faculty_ids') from error
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
        row = db_fetch.get_exam(exam_id)
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
        deleted = db_fetch.delete_exam(exam_id)
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
        course = db_fetch.fetch_course(body.course_id)
    except db_fetch.DatabaseError as error:
        raise _db_error(error) from error
    if course is None:
        raise _fail(422, 'Select a course.', 'course_id')
    picked = [f['name'] for f in course['faculty'] if f['id'] in set(body.faculty_ids)]
    try:
        section = academic.normalize_section(body.section)
    except ValueError as error:
        raise _fail(422, str(error), 'section') from error
    row = {
        'course_code': course['code'], 'course_title': course['title'], 'exam_type': body.exam_type,
        'exam_date': body.exam_date.isoformat(),
        'exam_time': body.exam_time.isoformat() if body.exam_time else None,
        'section': section, 'syllabus': body.syllabus, 'venue': body.venue,
        'remarks': body.remarks, 'notes_link': body.notes_link,
        'faculty_names': picked or [f['name'] for f in course['faculty']],
        'faculty_source': 'exam' if picked else 'course',
    }
    return {'text': formatter.format_exam(row, [], today=dr.today_local())}
