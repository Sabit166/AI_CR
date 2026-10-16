"""Turn a parsed intent into one deterministic exam_details query and run it.

No LLM involvement here: course/faculty ids come from the resolver, date ranges
from date_ranges.py (Asia/Dhaka), and filtering/sorting happen in PostgreSQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

import date_ranges as dr
from db_fetch import ExamQuery

from .catalog import Catalog
from .intent import Intent
from .resolver import CourseResolution, FacultyResolution, resolve_courses, resolve_faculty_mention

# Upper bound for list-style answers. We fetch one extra row to detect overflow,
# so later records are never dropped silently.
LIST_LIMIT = 60

BASE_FIELDS = ('id', 'course_code', 'course_title', 'course_type', 'exam_type', 'exam_date', 'exam_time', 'section',
               'course_section')
FIELD_COLUMNS = {
    'date': (),
    'time': (),
    'section': (),
    'syllabus': ('syllabus',),
    'faculty': ('faculty_names', 'faculty_source', 'section_faculty'),
    'venue': ('venue',),
    'notes_link': ('notes_link',),
    'remarks': ('remarks',),
}
SUMMARY_FIELDS = ('syllabus', 'faculty_names', 'faculty_source', 'section_faculty', 'venue', 'remarks', 'notes_link')


class ExamRepository(Protocol):
    def query_exams(self, query: ExamQuery) -> list[dict]: ...


@dataclass
class Plan:
    status: str                               # ok | clarify_course | unknown_course | clarify_faculty | unknown_faculty
    class_id: int | None = None               # the class (Discord channel) asking
    mode: str = 'range'                       # range | next | upcoming | recent | match
    date_range: dr.DateRange | None = None
    label: str = ''                           # human description of the period, e.g. "next week"
    note: str | None = None                   # e.g. weekend explanation
    course_ids: list[int] | None = None
    exam_types: list[str] | None = None
    faculty_ids: list[int] | None = None
    section: str | None = None
    select: tuple[str, ...] = BASE_FIELDS + SUMMARY_FIELDS
    requested_fields: list[str] = field(default_factory=list)
    course_resolution: CourseResolution | None = None
    faculty_resolutions: list[FacultyResolution] = field(default_factory=list)


@dataclass
class Result:
    plan: Plan
    rows: list[dict]
    truncated: bool = False
    next_available: dict | None = None        # when the range is empty: the next upcoming matching exam


def plan_query(intent: Intent, message: str, catalog: Catalog, now: datetime, class_id: int | None = None) -> Plan:
    plan = _plan(intent, message, catalog, now)
    plan.class_id = class_id
    return plan


def _plan(intent: Intent, message: str, catalog: Catalog, now: datetime) -> Plan:
    today = now.date()

    resolution = resolve_courses(intent.course_mentions, message, catalog)
    if resolution.ambiguous and intent.exam_types:
        # "next Database CT": a CT only exists for Theoretical courses, which may settle it.
        allowed_types = {t.course_type for t in catalog.exam_types if t.name in intent.exam_types}
        for result in resolution.ambiguous:
            narrowed = [c for c in result.courses if c.course_type in allowed_types]
            if len(narrowed) == 1:
                result.courses, result.ambiguous = narrowed, False
    if resolution.ambiguous:
        return Plan('clarify_course', course_resolution=resolution)
    if resolution.unmatched and not resolution.course_ids:
        return Plan('unknown_course', course_resolution=resolution)

    faculty_results = [resolve_faculty_mention(m, catalog) for m in intent.faculty_mentions]
    if any(r.ambiguous for r in faculty_results):
        return Plan('clarify_faculty', faculty_resolutions=faculty_results)
    if any(not r.faculty for r in faculty_results):
        return Plan('unknown_faculty', faculty_resolutions=faculty_results)

    plan = Plan('ok', course_resolution=resolution, faculty_resolutions=faculty_results)
    plan.course_ids = resolution.course_ids or None
    plan.exam_types = intent.exam_types or None
    plan.faculty_ids = [f.id for r in faculty_results for f in r.faculty] or None
    plan.section = intent.section
    plan.requested_fields = intent.fields
    if intent.fields:
        extra = tuple(col for f in intent.fields for col in FIELD_COLUMNS.get(f, ()))
        plan.select = tuple(dict.fromkeys(BASE_FIELDS + extra))

    _apply_time_scope(plan, intent, today)
    return plan


def _apply_time_scope(plan: Plan, intent: Intent, today: date) -> None:
    scope = intent.time
    kind = scope.kind

    def fixed(start: date, end: date, label: str) -> None:
        plan.mode = 'range'
        plan.date_range = dr.DateRange(start, end)
        plan.label = label

    if kind == 'today':
        fixed(today, today, 'today')
    elif kind == 'tomorrow':
        fixed(today + timedelta(days=1), today + timedelta(days=1), 'tomorrow')
    elif kind == 'day_after_tomorrow':
        day = today + timedelta(days=2)
        fixed(day, day, 'the day after tomorrow')
    elif kind == 'in_days' and scope.days is not None:
        day = today + timedelta(days=scope.days)
        fixed(day, day, f'in {scope.days} days')
    elif kind == 'this_week':
        remaining = dr.this_week_remaining(today)
        if remaining is None:
            week = dr.next_week(today)
            plan.note = (
                f'The academic week (Sunday–Thursday) is already over, so nothing is left this week. '
                f'Here is next week instead.'
            )
            fixed(week.start, week.end, 'next week')
        else:
            fixed(remaining.start, remaining.end, 'the rest of this week' if remaining.start != dr.academic_week_of(today).start else 'this week')
    elif kind == 'next_week':
        week = dr.next_week(today)
        fixed(week.start, week.end, 'next week')
    elif kind == 'weekday' and scope.weekday:
        day = dr.next_weekday(today, scope.weekday)
        fixed(day, day, 'today' if day == today else scope.weekday.capitalize())
    elif kind == 'weekday_range' and scope.weekday and scope.end_weekday:
        r = dr.weekday_range(today, scope.weekday, scope.end_weekday)
        fixed(r.start, r.end, f'{scope.weekday.capitalize()} to {scope.end_weekday.capitalize()}')
    elif kind == 'date' and scope.day and scope.month:
        try:
            day = dr.resolve_calendar_date(today, scope.day, scope.month, scope.year)
        except ValueError:
            plan.mode = 'match'
            plan.note = "That date doesn't exist, so I searched without it."
            return
        fixed(day, day, dr.format_day(day))
    elif kind == 'date_range' and scope.day and scope.month and scope.end_day:
        try:
            start = dr.resolve_calendar_date(today, scope.day, scope.month, scope.year)
            end = dr.resolve_calendar_date(start, scope.end_day, scope.end_month or scope.month, scope.end_year)
            if end < start:
                end = end.replace(year=end.year + 1)
            fixed(start, end, 'that period')
        except ValueError:
            plan.mode = 'match'
            plan.note = "I couldn't understand those dates, so I searched without them."
    elif kind == 'next':
        plan.mode = 'next'
    elif kind == 'upcoming':
        plan.mode = 'upcoming'
    elif kind == 'recent':
        plan.mode = 'recent'
    else:
        has_filter = plan.course_ids or plan.exam_types or plan.faculty_ids
        plan.mode = 'match' if has_filter else 'upcoming'


def _query(plan: Plan, **overrides) -> ExamQuery:
    base = dict(
        select=plan.select,
        class_id=plan.class_id,
        course_ids=tuple(plan.course_ids) if plan.course_ids else None,
        exam_types=tuple(plan.exam_types) if plan.exam_types else None,
        faculty_ids=tuple(plan.faculty_ids) if plan.faculty_ids else None,
        section=plan.section,
    )
    base.update(overrides)
    return ExamQuery(**base)


def _not_finished(row: dict, now: datetime) -> bool:
    """Today's exams whose start time has already passed are not 'next' any more."""
    if row['exam_date'] != now.date().isoformat() or not row.get('exam_time'):
        return True
    return row['exam_time'] >= now.strftime('%H:%M:%S')


def execute(plan: Plan, repo: ExamRepository, now: datetime) -> Result:
    today = now.date()

    if plan.mode == 'range':
        rows = repo.query_exams(_query(plan, date_from=plan.date_range.start, date_to=plan.date_range.end, limit=LIST_LIMIT + 1))
        result = Result(plan, rows[:LIST_LIMIT], truncated=len(rows) > LIST_LIMIT)
        if not rows:
            result.next_available = _next_after(plan, repo, plan.date_range.end + timedelta(days=1))
        return result

    if plan.mode == 'next':
        rows = [r for r in repo.query_exams(_query(plan, date_from=today, limit=LIST_LIMIT)) if _not_finished(r, now)]
        if not rows:
            return Result(plan, [])
        first_day = rows[0]['exam_date']
        return Result(plan, [r for r in rows if r['exam_date'] == first_day])

    if plan.mode == 'recent':
        rows = repo.query_exams(_query(plan, date_to=today - timedelta(days=1), descending=True, limit=10))
        if not rows:
            return Result(plan, [])
        last_day = rows[0]['exam_date']
        return Result(plan, list(reversed([r for r in rows if r['exam_date'] == last_day])))

    if plan.mode == 'upcoming':
        rows = [r for r in repo.query_exams(_query(plan, date_from=today, limit=LIST_LIMIT + 1)) if _not_finished(r, now)]
        return Result(plan, rows[:LIST_LIMIT], truncated=len(rows) > LIST_LIMIT)

    # 'match': specific course/type/teacher, no time given -> upcoming ones, else the most recent past ones
    upcoming = [r for r in repo.query_exams(_query(plan, date_from=today, limit=LIST_LIMIT + 1)) if _not_finished(r, now)]
    if upcoming:
        return Result(plan, upcoming[:LIST_LIMIT], truncated=len(upcoming) > LIST_LIMIT)
    plan.mode = 'match_past'
    past = repo.query_exams(_query(plan, date_to=today - timedelta(days=1), descending=True, limit=5))
    return Result(plan, list(reversed(past)))


def _next_after(plan: Plan, repo: ExamRepository, start: date) -> dict | None:
    rows = repo.query_exams(_query(plan, select=BASE_FIELDS, date_from=start, limit=1))
    return rows[0] if rows else None
