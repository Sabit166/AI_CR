"""Student-message intent extraction (/ask), rule-based: no AI service is called.

`heuristic_parse` turns the question into a typed `Intent`: course/teacher
mentions, exam types, the kind of time range and the requested fields.
Resolution against the database and all date arithmetic happen
deterministically afterwards (resolver.py, retrieval.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = ('exam_query', 'greeting', 'off_topic')

TIME_KINDS = (
    'none',                # no time constraint expressed
    'next',                # "next exam", "next CT" -> earliest upcoming date
    'upcoming',            # "all upcoming exams"
    'recent',              # "last CT", "previous exam"
    'today',
    'tomorrow',
    'day_after_tomorrow',
    'in_days',             # "in 3 days" -> days
    'this_week',           # remaining days of the current Sun-Thu week
    'next_week',           # next Sun-Thu week
    'date',                # explicit calendar date -> day/month[/year]
    'date_range',          # explicit calendar range -> day/month[/year] .. end_day/end_month[/end_year]
    'weekday',             # "on Monday" -> weekday
    'weekday_range',       # "from Sunday to Thursday" -> weekday .. end_weekday
)

FIELDS = ('date', 'time', 'syllabus', 'faculty', 'venue', 'section', 'notes_link', 'remarks')
WEEKDAY_NAMES = ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday')


@dataclass
class TimeScope:
    kind: str = 'none'
    day: int | None = None
    month: int | None = None
    year: int | None = None
    end_day: int | None = None
    end_month: int | None = None
    end_year: int | None = None
    weekday: str | None = None
    end_weekday: str | None = None
    days: int | None = None


@dataclass
class Intent:
    category: str = 'exam_query'
    course_mentions: list[str] = field(default_factory=list)
    faculty_mentions: list[str] = field(default_factory=list)
    exam_types: list[str] = field(default_factory=list)
    section: str | None = None
    time: TimeScope = field(default_factory=TimeScope)
    fields: list[str] = field(default_factory=list)   # empty = full summary
    source: str = 'heuristic'


# ---------------------------------------------------------------------------
# Rule-based parsing
# ---------------------------------------------------------------------------
_MONTHS = {
    m: i for i, names in enumerate((
        (), ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'), ('may',),
        ('jun', 'june'), ('jul', 'july'), ('aug', 'august'), ('sep', 'sept', 'september'),
        ('oct', 'october'), ('nov', 'november'), ('dec', 'december'),
    )) for m in names
}
_NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, '1': 1, '2': 2, '3': 3}
_WD = r'(sunday|monday|tuesday|wednesday|thursday|friday|saturday|sun|mon|tue|tues|wed|thu|thur|thurs|fri|sat)'
_WD_FULL = {w[:3]: w for w in WEEKDAY_NAMES}
_HONORIFICS = r'(?:sir|madam|mam|ma\'am|maam|miss|apu|bhai)'

_GREETING_RE = re.compile(r'^\s*(hi+|hello|hey|salam|assalamu ?alaikum|thanks|thank you|thx|help|good (morning|evening|night))\b[\s!.?]*$', re.I)
_EXAM_HINT_RE = re.compile(
    r'\b(exam|exams|ct|class ?tests?|test|quiz|syllabus|schedule|routine|week|today|tomorrow|mid|midterm|presentation|'
    r'evaluation|lab|project|update|updates|viva|course|courses|teacher|faculty|sir|madam|section|venue|room|notes?)\b', re.I)


def heuristic_parse(message: str, exam_type_names: list[str]) -> Intent:
    text = message.lower()
    intent = Intent(source='heuristic')

    if _GREETING_RE.match(message):
        intent.category = 'greeting'
        return intent

    # Exam types
    types: list[str] = []
    numbered = re.findall(r'\b(?:ct|class\s*test)\s*-?\s*(1|2|3|one|two|three)\b', text)
    for n in numbered:
        types.append(f'CT {_NUMBER_WORDS[n]}')
    if not numbered and re.search(r'\b(?:ct|cts|class\s*tests?)\b', text):
        types += ['CT 1', 'CT 2', 'CT 3']
    for pattern, name in (
        (r'\bproject\s*update', 'Project Update'),
        (r'\bevaluation', 'Evaluation'),
        (r'\bonline\s*(?:exam|test)?\b', 'Online Exam'),
        (r'\b(?:project\s*)?presentation', 'Project Presentation'),
        (r'\blab\s*(?:test|exam)', 'Lab Test'),
        (r'\bmid(?:term)?\b', 'Mid'),
    ):
        if re.search(pattern, text):
            types.append(name)
    intent.exam_types = [t for t in dict.fromkeys(types) if t in exam_type_names]

    intent.time = _heuristic_time(text)

    # Fields
    fields = []
    if re.search(r'\b(syllabus|topics?|portion|chapters?|coverage)\b', text):
        fields.append('syllabus')
    if re.search(r'\b(when|date|which day|what day)\b', text):
        fields += ['date', 'time']
    if re.search(r'\b(what time|time|at what)\b', text):
        fields.append('time')
    if re.search(r'\b(teacher|faculty|who|instructor)\b', text):
        fields.append('faculty')
    if re.search(r'\b(venue|room|where|location)\b', text):
        fields.append('venue')
    if re.search(r'\b(notes?|link|drive)\b', text):
        fields.append('notes_link')
    intent.fields = list(dict.fromkeys(fields))

    section = re.search(r'\b(?:section|sec)\s*-?\s*([a-z0-9]{1,3})\b', text)
    if section:
        intent.section = section.group(1).upper()

    intent.faculty_mentions = [m.strip() for m in re.findall(rf'([a-z][a-z.]+(?:\s+[a-z][a-z.]+)?)\s+{_HONORIFICS}\b', text)]

    has_signal = intent.exam_types or intent.time.kind != 'none' or intent.fields or _EXAM_HINT_RE.search(text)
    intent.category = 'exam_query' if has_signal else 'off_topic'
    return intent


def _heuristic_time(text: str) -> TimeScope:
    if re.search(r'\bnext\s+week|\bcoming\s+week|\bupcoming\s+week', text):
        return TimeScope('next_week')
    if re.search(r'\bthis\s+week|\bleft\s+this|\brest of (the|this) week|\bremaining .*week', text):
        return TimeScope('this_week')
    if re.search(r'\bday after tomorrow\b', text):
        return TimeScope('day_after_tomorrow')
    if re.search(r'\btomorrow|\btmrw|\btmr\b', text):
        return TimeScope('tomorrow')
    if re.search(r'\btoday|\btonight', text):
        return TimeScope('today')
    if m := re.search(r'\bin\s+(\d{1,2})\s+days?\b', text):
        return TimeScope('in_days', days=int(m.group(1)))

    if m := re.search(rf'\b(?:from\s+)?{_WD}\s*(?:to|-|till|until|through)\s*{_WD}\b', text):
        return TimeScope('weekday_range', weekday=_WD_FULL[m.group(1)[:3]], end_weekday=_WD_FULL[m.group(2)[:3]])

    month_names = '|'.join(sorted(_MONTHS, key=len, reverse=True))
    if m := re.search(rf'\b(\d{{4}})-(\d{{1,2}})-(\d{{1,2}})\b', text):
        return TimeScope('date', year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
    if m := re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\b(?:\s+(\d{{4}}))?', text):
        return TimeScope('date', day=int(m.group(1)), month=_MONTHS[m.group(2)], year=int(m.group(3)) if m.group(3) else None)
    if m := re.search(rf'\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?', text):
        return TimeScope('date', day=int(m.group(2)), month=_MONTHS[m.group(1)], year=int(m.group(3)) if m.group(3) else None)
    if m := re.search(r'\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}))?\b', text):
        return TimeScope('date', day=int(m.group(1)), month=int(m.group(2)), year=int(m.group(3)) if m.group(3) else None)

    if m := re.search(rf'\b(?:on|this|next|coming)?\s*{_WD}\b', text):
        return TimeScope('weekday', weekday=_WD_FULL[m.group(1)[:3]])

    if re.search(r'\b(last|previous|recent|past|already)\b', text):
        return TimeScope('recent')
    if re.search(r'\b(all|remaining|upcoming exams|future)\b', text) and re.search(r'\b(upcoming|remaining|future|left)\b', text):
        return TimeScope('upcoming')
    if re.search(r'\b(next|upcoming|coming|soon)\b', text):
        return TimeScope('next')
    return TimeScope('none')
