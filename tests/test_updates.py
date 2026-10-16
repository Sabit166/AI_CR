"""Discord update messages: content, escaping, day selection and splitting."""
from datetime import date

import pytest

import db_fetch
import updates
from conftest import CLASS_ID, FakeRepo, clock_at, exam_row

TUESDAY = '2026-10-13T10:00'


@pytest.fixture
def rows():
    return [
        exam_row(1, 1, 'CT 1', '2026-10-13', exam_time='09:00:00'),              # today, already started at 10:00
        exam_row(2, 2, 'CT 2', '2026-10-15', exam_time='14:00:00', syllabus='Ch 1\nCh 2', venue='Room 301'),
        exam_row(3, 3, 'Lab Test', '2026-10-15', exam_time='09:30:00', section='A',
                 notes_link='https://drive.example/notes'),
        exam_row(4, 4, 'Mid', '2026-10-19', exam_time=None, syllabus='All chapters'),
        exam_row(5, 6, 'CT 1', '2026-10-21', exam_time='11:00:00', course_section='B'),
        {**exam_row(9, 1, 'CT 3', '2026-10-15', syllabus='Other class'), 'class_id': 2},
    ]


@pytest.fixture
def repo(rows, monkeypatch):
    fake = FakeRepo(rows)
    monkeypatch.setattr(db_fetch, 'query_exams', fake.query_exams)
    return fake


def test_next_exam_day_has_every_exam_of_that_day(repo):
    update = updates.next_exam_day_update(CLASS_ID, clock_at(TUESDAY)())
    text = '\n'.join(update.messages)
    assert update.exam_count == 2
    assert 'Thursday, 15 October 2026' in text and '2 exams' in text
    # Ordered by time; the 09:00 exam that already started today is not "next".
    assert text.index('CSE-464') < text.index('CSE-427') and 'CSE-415' not in text
    assert '9:30 AM' in text and '2:00 PM' in text and 'Class Section A' in text and 'Room 301' in text
    assert 'Other class' not in text and all(q.class_id == CLASS_ID for q in repo.queries)


def test_next_exam_day_is_today_before_the_exam_starts(repo):
    update = updates.next_exam_day_update(CLASS_ID, clock_at('2026-10-13T08:00')())
    assert update.exam_count == 1 and 'Today · Tuesday, 13 October 2026' in update.messages[0]


def test_next_exam_notes(repo):
    text = '\n'.join(updates.next_exam_day_update(CLASS_ID, clock_at(TUESDAY)(), notes_only=True).messages)
    assert 'Notes for the next exam day' in text
    assert '🔗 Notes: <https://drive.example/notes>' in text and 'No notes link posted yet' in text
    assert 'Syllabus' not in text


def test_this_week_is_today_to_thursday(repo):
    update = updates.week_update(CLASS_ID, 'this', clock_at(TUESDAY)())
    text = '\n'.join(update.messages)
    assert update.exam_count == 3 and "This week's exams" in text
    assert 'Tuesday, 13 October 2026 – Thursday, 15 October 2026' in text
    assert 'Mid' not in text


def test_next_week(repo):
    text = '\n'.join(updates.week_update(CLASS_ID, 'next', clock_at(TUESDAY)()).messages)
    assert 'Sunday, 18 October 2026 – Thursday, 22 October 2026' in text
    assert 'Mid' in text and 'time not posted' in text and 'Course Section B' in text
    assert text.index('Monday, 19 October') < text.index('Wednesday, 21 October')


@pytest.mark.parametrize('at', ['2026-10-16T10:00', '2026-10-17T10:00'])
def test_this_week_on_the_weekend_shows_next_week(repo, at):
    text = updates.week_update(CLASS_ID, 'this', clock_at(at)()).messages[0]
    assert 'is over' in text and "Next week's exams" in text


def test_empty_week_says_so(monkeypatch):
    monkeypatch.setattr(db_fetch, 'query_exams', FakeRepo([]).query_exams)
    update = updates.week_update(CLASS_ID, 'next', clock_at(TUESDAY)())
    assert update.exam_count == 0 and 'No exams have been posted' in update.messages[0]
    assert updates.next_exam_day_update(CLASS_ID, clock_at(TUESDAY)()).messages == ['No upcoming exams have been posted yet.']


def test_reminder_only_when_there_are_exams(repo):
    assert updates.reminder_update(CLASS_ID, date(2026, 10, 14)).messages == []
    reminder = updates.reminder_update(CLASS_ID, date(2026, 10, 15))
    assert reminder.exam_count == 2 and 'Reminder: 2 exams tomorrow' in reminder.messages[0]


def test_cr_text_cannot_inject_discord_formatting():
    row = exam_row(1, 1, 'CT 1', '2026-10-20', syllabus='# Big\n**bold** _it_ @everyone [x](https://evil) > quote',
                   remarks='`code` ||spoiler||', venue='-# tiny')
    text = updates.format_exam(row)
    assert '\\# Big' in text and '\\*\\*bold\\*\\*' in text and '\\_it\\_' in text
    assert '\\[x\\](https://evil)' in text and '\\> quote' in text
    assert '\\`code\\`' in text and '\\|\\|spoiler\\|\\|' in text and '\\-# tiny' in text


def test_numbered_syllabus_stays_a_list():
    text = updates.format_exam(exam_row(1, 1, 'CT 1', '2026-10-20', syllabus='1. Trees\n2. Graphs'))
    assert '> 1. Trees\n> 2. Graphs' in text


def test_unsafe_notes_link_is_not_shown():
    assert 'javascript' not in updates.format_exam(exam_row(1, 1, 'CT 1', '2026-10-20', notes_link='javascript:alert(1)'))


def test_both_sections_show_each_teacher():
    text = updates.format_exam(exam_row(1, 1, 'CT 1', '2026-10-20'))
    assert 'Section A: Nazmul Hasan · Section B: Fairooz Tasnia' in text


def test_long_week_splits_under_discord_limit(monkeypatch):
    many = [exam_row(i, 3, 'Lab Test', f'2026-10-{18 + i % 5:02d}', section=str(i), syllabus='x' * 300) for i in range(1, 25)]
    monkeypatch.setattr(db_fetch, 'query_exams', FakeRepo(many).query_exams)
    update = updates.week_update(CLASS_ID, 'next', clock_at(TUESDAY)())
    assert len(update.messages) > 1 and all(len(m) <= 2000 for m in update.messages)
    assert update.exam_count == 24 and sum(m.count('📘') for m in update.messages) == 24
