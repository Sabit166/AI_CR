"""Deterministic, grounded answer text.

Every fact in a reply comes straight from a database row; nothing is generated.
Missing values are stated as missing. Long replies are split on record
boundaries so Messenger's 2000-character limit never cuts a record off.
"""
from __future__ import annotations

from datetime import date, datetime

import date_ranges as dr

from .catalog import Catalog
from .retrieval import Plan, Result

MESSENGER_LIMIT = 2000
CHUNK_BUDGET = 1900  # headroom for the "(1/3)" marker

HELP_TEXT = (
    "Hi! I'm the class exam assistant. Ask me things like:\n"
    "• What exams do we have next week?\n"
    "• What's left this week?\n"
    "• When is the next CT of <course>?\n"
    "• Syllabus for tomorrow's exam\n"
    "• All upcoming exams of <course code>"
)
OFF_TOPIC_TEXT = (
    "I can only help with exam information — dates, syllabus, teachers and venues for your courses. "
    "Try: \"What exams do we have next week?\""
)
DB_ERROR_TEXT = (
    "Sorry, I couldn't reach the exam database just now, so I can't confirm anything. "
    "Please try again in a minute."
)
GENERIC_ERROR_TEXT = "Sorry, something went wrong while looking that up. Please try again in a minute."


def _time_text(value: str | None) -> str | None:
    if not value:
        return None
    t = datetime.strptime(value[:5], '%H:%M')
    return t.strftime('%I:%M %p').lstrip('0')


def _date_text(value: str) -> str:
    return dr.format_day(date.fromisoformat(value))


def format_exam(row: dict, requested: list[str], *, today: date | None = None) -> str:
    """One record. `requested` empty -> full summary; otherwise identity + requested fields."""
    show_all = not requested
    lines = [f"📘 {row['course_code']} · {row['course_title']}"]

    type_line = f"📝 {row['exam_type']}"
    # Theoretical exams are per course section; Sessional tests are per class section.
    if row.get('section'):
        type_line += f" · Class Section {row['section']}"
    elif row.get('course_section'):
        type_line += f" · Course Section {row['course_section']}"
    elif row.get('course_type') == 'Theoretical':
        type_line += ' · Course Sections A & B'
    elif row.get('course_type') == 'Sessional':
        type_line += ' · Class Sections A & B (together)'
    lines.append(type_line)

    when = _date_text(row['exam_date'])
    exam_time = _time_text(row.get('exam_time'))
    if exam_time:
        when += f' · {exam_time}'
    elif show_all or 'time' in requested:
        when += ' · time not posted'
    if today is not None and row['exam_date'] == today.isoformat():
        when += ' (today)'
    lines.append(f'🗓 {when}')

    def wanted(name: str) -> bool:
        return show_all or name in requested

    if wanted('syllabus') and 'syllabus' in row:
        syllabus = (row.get('syllabus') or '').strip()
        lines.append(f'📖 Syllabus:\n{syllabus}' if syllabus else '📖 Syllabus: not posted yet')
    if wanted('faculty') and 'faculty_names' in row:
        names = row.get('faculty_names') or []
        # Per-section teachers, unless the exam carries its own (pre-course-section) faculty picks.
        by_section = [] if row.get('faculty_source') == 'exam' else row.get('section_faculty') or []
        label = 'Course faculty' if row.get('faculty_source') == 'course' and not by_section else 'Faculty'
        if len(by_section) > 1 and len({item['name'] for item in by_section}) > 1:
            lines.append('👤 Faculty: ' + ' · '.join(f"Course Section {i['section']}: {i['name']}" for i in by_section))
        elif names:
            lines.append(f"👤 {label}: {', '.join(names)}")
        elif not show_all:
            lines.append('👤 Faculty: not posted')
    if wanted('venue') and 'venue' in row:
        if row.get('venue'):
            lines.append(f"📍 Venue: {row['venue']}")
        elif not show_all:
            lines.append('📍 Venue: not posted')
    if wanted('notes_link') and 'notes_link' in row:
        if row.get('notes_link'):
            lines.append(f"🔗 Notes: {row['notes_link']}")
        elif not show_all:
            lines.append('🔗 Notes: no link posted')
    if wanted('remarks') and row.get('remarks'):
        lines.append(f"ℹ️ {row['remarks'].strip()}")
    return '\n'.join(lines)


def _subject(plan: Plan, catalog: Catalog) -> str:
    """'CT 2 for CSE-415 (Human Computer Interface)' / 'exam for section A' / 'exam'."""
    parts = []
    if plan.course_ids:
        names = [f'{c.code} ({c.title})' for c in (catalog.course_by_id(i) for i in plan.course_ids) if c]
        parts.append('for ' + ', '.join(names))
    if plan.faculty_resolutions:
        parts.append('with ' + ', '.join(f.name for r in plan.faculty_resolutions for f in r.faculty))
    if plan.section:
        parts.append(f'for section {plan.section}')
    types = list(plan.exam_types or [])
    if {'CT 1', 'CT 2', 'CT 3'} <= set(types):
        types = ['CT'] + [t for t in types if t not in ('CT 1', 'CT 2', 'CT 3')]
    head = ' / '.join(types) if types else 'exam'
    return ' '.join([head, *parts])


def format_result(result: Result, catalog: Catalog, today: date) -> list[str]:
    plan = result.plan
    rows = result.rows
    subject = _subject(plan, catalog)
    noun = subject if plan.exam_types else subject.replace('exam', 'exam information', 1)
    period = ''
    if plan.date_range is not None:
        formatted = dr.format_range(plan.date_range)
        period = formatted if plan.label == formatted else f'{plan.label} ({formatted})'

    intro: list[str] = []
    if plan.note:
        intro.append(plan.note)

    if not rows:
        if plan.mode == 'range':
            text = f'No {noun} has been posted for {period}.'
            if result.next_available:
                nxt = result.next_available
                text += (f"\nThe next one posted is {nxt['course_code']} {nxt['exam_type']} on "
                         f"{_date_text(nxt['exam_date'])}.")
        elif plan.mode == 'recent':
            text = f'I could not find any past {subject} records.'
        else:
            text = f'No upcoming {noun} has been posted yet.'
        return split_message('\n\n'.join([*intro, text]))

    count = len(rows)
    plural = 's' if count != 1 else ''
    if plan.mode == 'range':
        header = f'🗓 {count} exam{plural} for {period}:'
        if subject != 'exam':
            header = f'🗓 {count} exam{plural} ({subject}) for {period}:'
    elif plan.mode == 'next':
        header = f'Next {subject}:' if count == 1 else f'Next {subject} — {count} on the same day:'
    elif plan.mode == 'recent':
        header = f'Most recent {subject}:'
    elif plan.mode == 'match_past':
        header = f'No upcoming {subject} is posted. Most recent:'
    else:
        header = f'Upcoming {subject} — {count}:'

    blocks = [format_exam(row, plan.requested_fields, today=today) for row in rows]
    if result.truncated:
        blocks.append(f'…and more. Showing the first {len(rows)}; please ask about a shorter period or a specific course.')
    return split_message('\n\n'.join([*intro, header]), blocks)


def format_clarification(plan: Plan) -> str:
    if plan.status == 'clarify_course':
        lines = []
        for result in plan.course_resolution.ambiguous:
            options = '\n'.join(f'• {c.code} — {c.title}' for c in result.courses)
            lines.append(f'"{result.mention}" could mean:\n{options}')
        return '\n\n'.join(lines) + '\n\nWhich one do you mean? Reply with the course code.'
    if plan.status == 'clarify_faculty':
        lines = []
        for result in plan.faculty_resolutions:
            if result.ambiguous:
                lines.append(f'"{result.mention}" could be: ' + ', '.join(f.name for f in result.faculty))
        return '\n'.join(lines) + '\nWhich teacher do you mean? Please use their full name.'
    return ''


def format_unknown(plan: Plan, catalog: Catalog) -> str:
    if plan.status == 'unknown_course':
        missing = ', '.join(f'"{r.mention}"' for r in plan.course_resolution.unmatched)
        if not catalog.courses:
            return f"I couldn't find {missing}: no courses have been configured yet."
        courses = '\n'.join(f'• {c.code} — {c.title}' for c in catalog.courses)
        return f"I couldn't find a course matching {missing}. This term's courses are:\n{courses}"
    missing = ', '.join(f'"{r.mention}"' for r in plan.faculty_resolutions if not r.faculty)
    return f"I couldn't find a teacher matching {missing} among this term's course faculty."


def split_message(intro: str, blocks: list[str] | None = None, budget: int = CHUNK_BUDGET) -> list[str]:
    """Pack intro + record blocks into messages <= budget chars without splitting a block,
    unless a single block is itself too long (then it is split on line boundaries)."""
    pieces: list[str] = []
    for block in [intro, *(blocks or [])]:
        if not block:
            continue
        if len(block) <= budget:
            pieces.append(block)
            continue
        current = ''
        for line in block.split('\n'):
            while len(line) > budget:
                if current:
                    pieces.append(current)
                    current = ''
                pieces.append(line[:budget])
                line = line[budget:]
            candidate = f'{current}\n{line}' if current else line
            if len(candidate) > budget:
                pieces.append(current)
                current = line
            else:
                current = candidate
        if current:
            pieces.append(current)

    messages: list[str] = []
    current = ''
    for piece in pieces:
        candidate = f'{current}\n\n{piece}' if current else piece
        if len(candidate) > budget:
            messages.append(current)
            current = piece
        else:
            current = candidate
    if current:
        messages.append(current)

    if len(messages) > 1:
        total = len(messages)
        messages = [f'{m}\n({i}/{total})' for i, m in enumerate(messages, 1)]
    return messages
