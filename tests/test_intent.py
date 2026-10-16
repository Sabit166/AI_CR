import pytest

from Chatbot.intent import heuristic_parse
from conftest import COURSES, EXAM_TYPES

TYPES = [t['name'] for t in EXAM_TYPES]


@pytest.mark.parametrize('message,kind', [
    ('What exams are scheduled next week?', 'next_week'),
    ("Give me next week's exam updates", 'next_week'),
    ('What exams do we have this week?', 'this_week'),
    ('What exams are left this week?', 'this_week'),
    ('What is happening tomorrow?', 'tomorrow'),
    ('exams today', 'today'),
    ('What exams are scheduled from Sunday to Thursday?', 'weekday_range'),
    ('What is the next Database CT?', 'next'),
    ('Give me all upcoming exams for this course', 'upcoming'),
    ('exam on 27 July', 'date'),
    ('anything on monday?', 'weekday'),
    ('syllabus of last CT of HCI', 'recent'),
    ('exams in 3 days', 'in_days'),
])
def test_heuristic_time_kinds(message, kind):
    assert heuristic_parse(message, TYPES).time.kind == kind


def test_heuristic_details():
    parsed = heuristic_parse('When is CSE-429 Class Test 2 for section b? syllabus please', TYPES)
    assert parsed.exam_types == ['CT 2']
    assert parsed.section == 'B'
    assert {'date', 'syllabus'} <= set(parsed.fields)
    assert parsed.category == 'exam_query'

    assert heuristic_parse('next CT', TYPES).exam_types == ['CT 1', 'CT 2', 'CT 3']
    assert heuristic_parse('lab test of DBMS lab', TYPES).exam_types == ['Lab Test']
    assert heuristic_parse('next exam of shahriar sir', TYPES).faculty_mentions == ['of shahriar']
    weekday = heuristic_parse('from sun to thu', TYPES).time
    assert (weekday.weekday, weekday.end_weekday) == ('sunday', 'thursday')


@pytest.mark.parametrize('message,category', [
    ('hi', 'greeting'), ('Thank you!', 'greeting'),
    ('what is the capital of France', 'off_topic'),
    ('next exam?', 'exam_query'),
])
def test_heuristic_category(message, category):
    assert heuristic_parse(message, TYPES).category == category
