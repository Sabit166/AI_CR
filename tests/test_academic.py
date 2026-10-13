import pytest

import academic

# Shared with tests/integration/test_db.py, which checks the SQL functions give the same answers.
CODE_VECTORS = [
    ('CSE-415', 'CSE-415', 'Theoretical'),
    ('cse 415', 'CSE-415', 'Theoretical'),
    ('CSE415', 'CSE-415', 'Theoretical'),
    ('cse_464', 'CSE-464', 'Sessional'),
    ('GEEM 433', 'GEEM-433', 'Theoretical'),
    (' eee-2100 ', 'EEE-2100', 'Sessional'),
    ('CSE-410', 'CSE-410', 'Sessional'),
    ('MATH-1001', 'MATH-1001', 'Theoretical'),
    ('CSE-415A', None, None),     # suffix: ambiguous -> rejected
    ('415', None, None),          # no department
    ('C-415', None, None),        # 1-letter prefix
    ('CSE-41', None, None),       # too few digits
    ('CSE-41500', None, None),    # too many digits
    ('CS E-415', None, None),
    ('', None, None),
]


@pytest.mark.parametrize('raw,code,course_type', CODE_VECTORS)
def test_parse_course_code(raw, code, course_type):
    parsed = academic.parse_course_code(raw)
    assert parsed.code == code
    assert parsed.course_type == course_type
    assert parsed.ok == (code is not None)
    if code is None:
        assert parsed.error


def test_parity_uses_number_not_ascii():
    # 'E' (ASCII 69) is odd, but EEE-2100's number is even -> Sessional
    assert academic.course_type_for_code('EEE-2100') == 'Sessional'
    assert academic.course_type_for_code('cse-415') is None  # only canonical codes are typed


@pytest.mark.parametrize('course_type,count,ok', [
    ('Theoretical', 2, True), ('Theoretical', 1, False), ('Theoretical', 3, False),
    ('Sessional', 3, True), ('Sessional', 4, True), ('Sessional', 2, False), ('Sessional', 5, False),
])
def test_faculty_count_rules(course_type, count, ok):
    assert (academic.faculty_count_error(course_type, count) is None) == ok


def test_section_normalization():
    assert academic.normalize_section(None) is None
    assert academic.normalize_section('  ') is None
    assert academic.normalize_section(' b ') == 'B'
    with pytest.raises(ValueError):
        academic.normalize_section('A; drop table')
