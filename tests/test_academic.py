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


@pytest.mark.parametrize('course_type,section_faculty,ok', [
    ('Theoretical', {'A': 1, 'B': 2}, True),
    ('Theoretical', {'A': 1, 'B': 1}, True),    # one teacher may take both course sections
    ('Theoretical', {'A': 1}, False),
    ('Theoretical', {}, False),
    ('Sessional', {}, True),
    ('Sessional', {'A': 1}, False),
])
def test_section_faculty_rules(course_type, section_faculty, ok):
    assert (academic.section_faculty_error(course_type, section_faculty) is None) == ok


def test_course_section_normalization():
    assert academic.normalize_course_section(None) is None
    assert academic.normalize_course_section(' ') is None
    assert academic.normalize_course_section(' b ') == 'B'
    with pytest.raises(ValueError):
        academic.normalize_course_section('C')
    assert academic.has_course_sections('Theoretical') and not academic.has_course_sections('Sessional')


def test_section_normalization():
    assert academic.normalize_section(None) is None
    assert academic.normalize_section('  ') is None
    assert academic.normalize_section(' b ') == 'B'
    with pytest.raises(ValueError):
        academic.normalize_section('A; drop table')


def test_sections_only_for_sessional():
    assert academic.has_sections('Sessional') is True
    assert academic.has_sections('Theoretical') is False
