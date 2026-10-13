"""Asia/Dhaka calendar helpers for relative-date questions.

All exam dates are stored as local (Asia/Dhaka) DATE + optional TIME, so ranges
here are inclusive [start, end] date pairs that map directly onto
`exam_date >= start AND exam_date <= end` in PostgREST. The LLM never does date
arithmetic; it only says *which* kind of range the student asked for.

Academic week = Sunday..Thursday. Friday and Saturday are the weekend.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TIMEZONE_NAME = 'Asia/Dhaka'
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

Clock = Callable[[], datetime]

# Python weekday(): Monday=0 ... Sunday=6
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
ACADEMIC_DAYS = ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday')


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


def now_local(clock: Clock | None = None) -> datetime:
    """Current time in Asia/Dhaka. `clock` must return an aware datetime (tests inject one)."""
    current = (clock or system_clock)()
    if current.tzinfo is None:
        raise ValueError('clock must return a timezone-aware datetime')
    return current.astimezone(TIMEZONE)


def today_local(clock: Clock | None = None) -> date:
    return now_local(clock).date()


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f'range end {self.end} is before start {self.start}')

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def academic_week_of(day: date) -> DateRange:
    """Sunday..Thursday of the week containing `day`. On Fri/Sat this is the week that just ended."""
    days_since_sunday = (day.weekday() + 1) % 7
    sunday = day - timedelta(days=days_since_sunday)
    return DateRange(sunday, sunday + timedelta(days=4))


def is_weekend(day: date) -> bool:
    return day.weekday() in (4, 5)  # Friday, Saturday


def this_week_remaining(today: date) -> DateRange | None:
    """Today..Thursday of the current academic week, or None on Friday/Saturday."""
    week = academic_week_of(today)
    if today > week.end:
        return None
    return DateRange(today, week.end)


def this_week_full(today: date) -> DateRange:
    return academic_week_of(today)


def next_week(today: date) -> DateRange:
    """The next Sunday..Thursday academic week (never the current one, even when asked on Sunday)."""
    sunday = academic_week_of(today).start + timedelta(days=7)
    return DateRange(sunday, sunday + timedelta(days=4))


def upcoming_or_current_week(today: date) -> DateRange:
    """Current academic week while it is running, otherwise the next one (used on the weekend)."""
    return this_week_full(today) if not is_weekend(today) else next_week(today)


def next_weekday(today: date, weekday: str) -> date:
    """Next occurrence of `weekday`, counting today."""
    target = WEEKDAYS.index(weekday.lower())
    return today + timedelta(days=(target - today.weekday()) % 7)


def weekday_range(today: date, start_weekday: str, end_weekday: str) -> DateRange:
    """'from Sunday to Thursday' etc.

    Anchored on the current academic week while it is running (so "Sunday to
    Thursday" asked on Tuesday means this week), otherwise on the next week.
    If the end weekday comes before the start, the range runs into the next week.
    """
    anchor = upcoming_or_current_week(today).start  # a Sunday
    start = anchor + timedelta(days=(WEEKDAYS.index(start_weekday.lower()) - anchor.weekday()) % 7)
    end = start + timedelta(days=(WEEKDAYS.index(end_weekday.lower()) - start.weekday()) % 7)
    return DateRange(start, end)


def resolve_calendar_date(today: date, day: int, month: int, year: int | None = None) -> date:
    """Resolve '27 July' style dates. Without a year: this year, unless that is more than
    ~6 months in the past, in which case next year (e.g. asking about '5 Jan' in December)."""
    if year is not None:
        return date(year, month, day)
    candidate = date(today.year, month, day)
    if (today - candidate).days > 183:
        candidate = date(today.year + 1, month, day)
    return candidate


def format_day(day: date) -> str:
    """'Monday, 3 August 2026'"""
    return f'{day.strftime("%A")}, {day.day} {day.strftime("%B %Y")}'


def format_range(r: DateRange) -> str:
    if r.start == r.end:
        return format_day(r.start)
    return f'{format_day(r.start)} – {format_day(r.end)}'
