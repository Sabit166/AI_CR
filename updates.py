"""Exam update messages for a class's Discord channel.

Used by the slash commands, the CR editor's "Post to Discord" buttons and the
automatic posts. Like the chatbot, every fact comes from exam_details rows and
nothing is generated. Text the CRs typed (syllabus, venue, remarks) is escaped
so it can't turn into Discord formatting, and messages are split under
Discord's 2000-character limit without cutting a record in half.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import date_ranges as dr
import db_fetch
from Chatbot.formatter import split_message

LIST_LIMIT = 60
UPDATE_FIELDS = (
    'id', 'course_code', 'course_title', 'course_type', 'exam_type', 'exam_date', 'exam_time', 'section',
    'course_section', 'syllabus', 'venue', 'remarks', 'notes_link', 'faculty_names', 'faculty_source',
    'section_faculty',
)

_MARKDOWN_RE = re.compile(r'([\\*_~`|>\[\]])')
_LINE_START_RE = re.compile(r'^(\s*)(#{1,3}\s|-#\s)', re.MULTILINE)  # headings; lists are fine as lists
_MASS_MENTION_RE = re.compile(r'@(everyone|here)', re.IGNORECASE)


@dataclass
class Update:
    """Message parts ready to post, plus whether any exam was found."""
    messages: list[str]
    exam_count: int


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def escape(text: str | None) -> str:
    """CR-typed text, shown literally in Discord (no bold, headings, links, quotes or
    @everyone/@here pings, even in a message that is allowed to ping everyone)."""
    escaped = _MARKDOWN_RE.sub(r'\\\1', (text or '').strip())
    escaped = _MASS_MENTION_RE.sub('@​\\1', escaped)  # zero-width space breaks the mention
    return _LINE_START_RE.sub(lambda m: m.group(1) + '\\' + m.group(2), escaped)


def _time_text(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.strptime(value[:5], '%H:%M').strftime('%I:%M %p').lstrip('0')


def _day_label(day: date, today: date) -> str:
    text = dr.format_day(day)
    if day == today:
        return f'Today · {text}'
    if day == today + timedelta(days=1):
        return f'Tomorrow · {text}'
    return text


def _sections(row: dict) -> str:
    # Theoretical exams are per course section; Sessional tests are per class section.
    if row.get('section'):
        return f"Class Section {row['section']}"
    if row.get('course_section'):
        return f"Course Section {row['course_section']}"
    if row.get('course_type') == 'Theoretical':
        return 'Course Sections A & B'
    return 'Whole class'


def _faculty(row: dict) -> str | None:
    by_section = [] if row.get('faculty_source') == 'exam' else row.get('section_faculty') or []
    if len(by_section) > 1 and len({item['name'] for item in by_section}) > 1:
        return ' · '.join(f"Section {i['section']}: {escape(i['name'])}" for i in by_section)
    names = row.get('faculty_names') or []
    return ', '.join(escape(n) for n in names) or None


def _link(url: str | None) -> str | None:
    # <...> keeps Discord from unfurling a large preview for every notes link.
    if not url or not re.match(r'^https?://\S+$', url):
        return None
    return f'<{url}>'


def format_exam(row: dict, *, notes_only: bool = False) -> str:
    """One exam as a Discord message block."""
    lines = [f"📘 **{escape(row['course_code'])} · {escape(row['course_title'])}** — {escape(row['exam_type'])}"]
    time_text = _time_text(row.get('exam_time')) or 'time not posted'
    when = f'🕘 {time_text} · {_sections(row)}'
    if row.get('venue') and not notes_only:
        when += f" · 📍 {escape(row['venue'])}"
    lines.append(when)

    link = _link(row.get('notes_link'))
    if notes_only:
        lines.append(f'🔗 Notes: {link}' if link else '🔗 No notes link posted yet')
        return '\n'.join(lines)

    syllabus = escape(row.get('syllabus'))
    if not syllabus:
        lines.append('📖 Syllabus: not posted yet')
    elif '\n' in syllabus:
        lines.append('📖 Syllabus:\n' + '\n'.join(f'> {line}' if line.strip() else '>' for line in syllabus.split('\n')))
    else:
        lines.append(f'📖 Syllabus: {syllabus}')
    faculty = _faculty(row)
    if faculty:
        lines.append(f'👤 {faculty}')
    if link:
        lines.append(f'🔗 Notes: {link}')
    if row.get('remarks'):
        lines.append(f"ℹ️ {escape(row['remarks'])}")
    return '\n'.join(lines)


def _day_blocks(rows: list[dict], today: date, *, notes_only: bool = False) -> list[str]:
    """One block per day: a day heading followed by that day's exams."""
    blocks: list[str] = []
    current: str | None = None
    for row in rows:
        if row['exam_date'] != current:
            current = row['exam_date']
            blocks.append(f"__**🗓 {_day_label(date.fromisoformat(current), today)}**__")
        blocks[-1] += '\n' + format_exam(row, notes_only=notes_only) + '\n'
    return [b.rstrip() for b in blocks]


def _count(n: int) -> str:
    return f"{n} exam{'s' if n != 1 else ''}"


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def _rows(class_id: int, start: date, end: date | None = None, limit: int = LIST_LIMIT + 1) -> list[dict]:
    return db_fetch.query_exams(db_fetch.ExamQuery(
        select=UPDATE_FIELDS, class_id=class_id, date_from=start, date_to=end, limit=limit,
    ))


def _not_finished(row: dict, now: datetime) -> bool:
    """Today's exams whose start time has passed no longer count as 'next'."""
    if row['exam_date'] != now.date().isoformat() or not row.get('exam_time'):
        return True
    return row['exam_time'] >= now.strftime('%H:%M:%S')


def next_exam_day_rows(class_id: int, now: datetime) -> list[dict]:
    """Every exam on the next day that has one (all of them, however many)."""
    rows = [r for r in _rows(class_id, now.date()) if _not_finished(r, now)]
    if not rows:
        return []
    first = rows[0]['exam_date']
    day_rows = [r for r in rows if r['exam_date'] == first]
    if len(day_rows) == len(rows) and len(rows) > LIST_LIMIT:
        day_rows = _rows(class_id, date.fromisoformat(first), date.fromisoformat(first), limit=200)
    return day_rows


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------
def week_update(class_id: int, which: str, now: datetime) -> Update:
    """'this': today..Thursday (on the weekend: next week, with a note). 'next': next Sun–Thu."""
    today = now.date()
    note = None
    if which == 'this':
        week = dr.this_week_remaining(today)
        title = "This week's exams"
        if week is None:
            week = dr.next_week(today)
            title = "Next week's exams"
            note = 'The academic week (Sunday–Thursday) is over, so here is next week.'
    elif which == 'next':
        week = dr.next_week(today)
        title = "Next week's exams"
    else:
        raise ValueError(which)

    rows = _rows(class_id, week.start, week.end)
    truncated = len(rows) > LIST_LIMIT
    rows = rows[:LIST_LIMIT]
    period = f'{dr.format_day(week.start)} – {dr.format_day(week.end)}' if week.start != week.end else dr.format_day(week.start)
    header = f'📅 **{title}** · {period}'
    if note:
        header = f'{note}\n{header}'
    if not rows:
        return Update(split_message(f'{header}\n\nNo exams have been posted for this period.'), 0)
    blocks = _day_blocks(rows, today)
    if truncated:
        blocks.append(f'…and more. Showing the first {LIST_LIMIT}; see the full list with /exams.')
    return Update(split_message(f'{header} — {_count(len(rows))}', blocks), len(rows))


def next_exam_day_update(class_id: int, now: datetime, *, notes_only: bool = False) -> Update:
    rows = next_exam_day_rows(class_id, now)
    if not rows:
        return Update(['No upcoming exams have been posted yet.'], 0)
    day = date.fromisoformat(rows[0]['exam_date'])
    if notes_only:
        header = f'🔗 **Notes for the next exam day** · {_day_label(day, now.date())}'
    else:
        header = f'⏭️ **Next exam day** · {_day_label(day, now.date())} — {_count(len(rows))}'
    blocks = [format_exam(r, notes_only=notes_only) for r in rows]
    return Update(split_message(header, blocks), len(rows))


def reminder_update(class_id: int, day: date) -> Update:
    """The day-before reminder: every exam on `day`. Empty when there are none."""
    rows = _rows(class_id, day, day, limit=200)
    if not rows:
        return Update([], 0)
    header = f'⏰ **Reminder: {_count(len(rows))} tomorrow** · {dr.format_day(day)}'
    return Update(split_message(header, [format_exam(r) for r in rows]), len(rows))


def exam_update(row: dict, now: datetime) -> Update:
    """A single exam, posted by a CR from the editor."""
    day = date.fromisoformat(row['exam_date'])
    header = f'📢 **Exam update** · {_day_label(day, now.date())}'
    return Update(split_message(header, [format_exam(row)]), 1)
