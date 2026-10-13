import pytest

from Chatbot.resolver import (
    codes_in_text, resolve_course_mention, resolve_courses, resolve_faculty_mention, scan_message_for_courses,
)
from conftest import make_catalog


@pytest.mark.parametrize('mention,codes', [
    ('CSE-415', ['CSE-415']),
    ('cse 415', ['CSE-415']),
    ('415', ['CSE-415']),
    ('Human Computer Interface', ['CSE-415']),
    ('human computer interface', ['CSE-415']),
    ('HCI', ['CSE-415']),
    ('hci', ['CSE-415']),
    ('DIP', ['CSE-427']),                      # configured alias
    ('image processing', ['CSE-427']),
    ('SDP', ['CSE-464']),
    ('SDP 2', ['CSE-464']),
    ('sdp ii', ['CSE-464']),
    ('Software Development Project-2', ['CSE-464']),   # alias from old spelling
    ('DBMS', ['CSE-305']),
    ('Database Management Systems Lab', ['CSE-306']),
    ('ethics', ['GEEM-433']),
    ('GEEM', ['GEEM-433']),
    ('human computer interfase', ['CSE-415']),  # typo -> fuzzy
    ('HCI CT', ['CSE-415']),                    # stray exam-type word
])
def test_resolves_single_course(mention, codes):
    result = resolve_course_mention(mention, make_catalog())
    assert [c.code for c in result.courses] == codes
    assert not result.ambiguous


def test_ambiguous_title_asks_instead_of_guessing():
    result = resolve_course_mention('database', make_catalog())
    assert result.ambiguous
    assert {c.code for c in result.courses} == {'CSE-305', 'CSE-306'}


def test_department_prefix_is_a_group_not_ambiguity():
    result = resolve_course_mention('CSE', make_catalog())
    assert result.group and not result.ambiguous
    assert len(result.courses) == 5


@pytest.mark.parametrize('mention', ['quantum physics', 'CSE-999', 'xyz'])
def test_unknown_course(mention):
    assert not resolve_course_mention(mention, make_catalog()).matched


def test_similar_titles_do_not_cross_match():
    catalog = make_catalog()
    assert [c.code for c in resolve_course_mention('Database Management Systems', catalog).courses] == ['CSE-305']
    assert [c.code for c in resolve_course_mention('Database Management Systems Lab', catalog).courses] == ['CSE-306']


def test_renamed_course_resolves_by_new_title_only():
    courses = [dict(c) for c in make_catalog_rows()]
    courses[0] = {**courses[0], 'title': 'Interaction Design'}
    catalog = make_catalog(courses)
    assert [c.code for c in resolve_course_mention('interaction design', catalog).courses] == ['CSE-415']
    assert not resolve_course_mention('human computer interface', catalog).matched


def make_catalog_rows():
    from conftest import COURSES
    return COURSES


def test_codes_in_message_are_added_even_if_llm_missed_them():
    resolution = resolve_courses([], 'when is the cse415 ct?', make_catalog())
    assert resolution.course_ids == [1]
    assert codes_in_text('CSE 427 and geem-433', {'CSE', 'GEEM'}) == ['CSE-427', 'GEEM-433']
    assert codes_in_text('exams on 2026-10-17 in 2026', {'CSE'}) == []
    assert codes_in_text('MAT101 and xyz 101', {'CSE'}) == ['MAT-101']


def test_scan_message_fallback():
    catalog = make_catalog()
    assert 'Human Computer Interface' in scan_message_for_courses('next human computer interface exam', catalog)
    assert 'hci' in scan_message_for_courses('next HCI CT', catalog)
    assert 'CSE-464' in scan_message_for_courses('cse 464 project update', catalog)


@pytest.mark.parametrize('mention,names', [
    ('Nazmul', ['Nazmul Hasan']),
    ('nazmul sir', ['Nazmul Hasan']),
    ('Maj Nazmul Hasan', ['Nazmul Hasan']),
    ('Fairooz madam', ['Fairooz Tasnia']),
    ('Nafisa', ['Nafisa Nawal']),
    ('of arif', ['Arif Bhuiyan']),
    ('Shahriar', ['Shahriar Kabir', 'Shahriar Sazzad']),   # ambiguous
    ('Rahim', []),
])
def test_faculty_resolution(mention, names):
    result = resolve_faculty_mention(mention, make_catalog())
    assert [f.name for f in result.faculty] == names


def test_longer_title_match_absorbs_shorter_title():
    from conftest import COURSES
    courses = COURSES + [{'id': 8, 'code': 'CSE-401', 'title': 'Human Computer', 'course_type': 'Theoretical',
                          'aliases': [], 'faculty': []}]
    mentions = scan_message_for_courses('next human computer interface exam', make_catalog(courses))
    assert mentions == ['Human Computer Interface']
