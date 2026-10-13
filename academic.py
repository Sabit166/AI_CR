"""Academic business rules shared by the CR API and the student agent.

Mirrors the SQL functions public.normalize_course_code / public.course_type_for_code
(see supabase/migrations) and AI_CR/src/lib/academic.js. Keep the three in sync;
tests/test_academic.py checks the Python side against the same vectors the
database integration test uses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

THEORETICAL = 'Theoretical'
SESSIONAL = 'Sessional'
COURSE_TYPES = (THEORETICAL, SESSIONAL)

# 2-5 letters, optional separator (space, hyphen, underscore), 3-4 digits.
_INPUT_CODE_RE = re.compile(r'^\s*([A-Za-z]{2,5})[\s_-]*([0-9]{3,4})\s*$')
CANONICAL_CODE_RE = re.compile(r'^[A-Z]{2,5}-[0-9]{3,4}$')

# Expected faculty counts per course type (inclusive range).
FACULTY_COUNT_RULES: dict[str, tuple[int, int]] = {
    THEORETICAL: (2, 2),
    SESSIONAL: (3, 4),
}

SECTION_RE = re.compile(r'^[A-Z0-9]{1,10}$')


@dataclass(frozen=True)
class CourseCode:
    code: str | None
    course_type: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


def normalize_course_code(raw: str | None) -> str | None:
    """'cse 415' / 'CSE_415' / 'geem433' -> 'CSE-415' / 'GEEM-433'; None if not a valid code."""
    if raw is None:
        return None
    match = _INPUT_CODE_RE.match(raw)
    if not match:
        return None
    return f'{match.group(1).upper()}-{match.group(2)}'


def course_type_for_code(code: str) -> str | None:
    """Parity of the numeric component's last digit: odd = Theoretical, even = Sessional."""
    if not CANONICAL_CODE_RE.match(code or ''):
        return None
    return SESSIONAL if int(code[-1]) % 2 == 0 else THEORETICAL


def parse_course_code(raw: str | None) -> CourseCode:
    if raw is None or not raw.strip():
        return CourseCode(None, None, 'Course code is required.')
    code = normalize_course_code(raw)
    if code is None:
        return CourseCode(
            None,
            None,
            f'"{raw.strip()}" is not a valid course code. Use letters followed by a 3-4 digit number, e.g. CSE-415.',
        )
    return CourseCode(code, course_type_for_code(code), None)


def faculty_count_error(course_type: str, count: int) -> str | None:
    low, high = FACULTY_COUNT_RULES[course_type]
    if low <= count <= high:
        return None
    expected = str(low) if low == high else f'{low} or {high}'
    return f'{course_type} courses normally have {expected} faculty members (selected {count}).'


def normalize_section(raw: str | None) -> str | None:
    """'' / None -> None (whole class); ' a ' -> 'A'. Raises ValueError for anything else."""
    if raw is None or not raw.strip():
        return None
    section = raw.strip().upper()
    if not SECTION_RE.match(section):
        raise ValueError('Section must be 1-10 letters or digits, e.g. A or B. Leave it empty for the whole class.')
    return section
