"""End-to-end agent behaviour against an in-memory repository with an injected clock.

Assertions check the actual date bounds sent to the database, the filters, and
the records returned — not just the reply wording.
"""
from datetime import date

import pytest

import db_fetch
from Chatbot.Chatbot import answer
from Chatbot.catalog import CatalogCache
from Chatbot.formatter import DB_ERROR_TEXT
from Chatbot.intent import Intent, TimeScope
from Chatbot.retrieval import execute, plan_query
from conftest import CLASS_ID, FakeRepo, clock_at, exam_row, make_catalog

TUESDAY = '2026-10-13T08:00'   # Tue 13 Oct 2026, 08:00 Dhaka

ROWS = [
    exam_row(1, 1, 'CT 2', '2026-10-13', '09:00:00', section='A', syllabus='Ch 1-3'),
    exam_row(2, 2, 'CT 1', '2026-10-14', '10:00:00'),
    exam_row(3, 3, 'Project Update', '2026-10-15', None, syllabus='Frontend', faculty_ids=[4]),
    exam_row(4, 4, 'CT 1', '2026-10-18', '09:00:00', syllabus='ER model\nNormalization', venue='Room 302'),
    exam_row(10, 2, 'CT 2', '2026-10-18', '09:00:00'),
    exam_row(5, 5, 'Lab Test', '2026-10-20', '14:00:00'),
    exam_row(6, 6, 'CT 2', '2026-10-22', '11:00:00', section='B'),
    exam_row(7, 1, 'CT 3', '2026-10-25', '09:00:00'),
    exam_row(8, 4, 'CT 2', '2026-11-01', '09:00:00'),
    exam_row(9, 1, 'CT 1', '2026-10-04', '09:00:00', syllabus='Intro'),
]


@pytest.fixture
def repo():
    return FakeRepo(list(ROWS))


def ask(message, repo, cache, at=TUESDAY):
    return answer(message, class_id=CLASS_ID, clock=clock_at(at), repo=repo, cache=cache)


def ids_in(reply_text, rows=ROWS):
    """Which fixture rows appear in the reply, in order of appearance."""
    found = []
    for row in rows:
        marker = f"{row['course_code']} · {row['course_title']}\n📝 {row['exam_type']}"
        pos = reply_text.find(marker)
        if pos >= 0:
            found.append((pos, row['id']))
    return [i for _, i in sorted(found)]


def date_bounds(query):
    return query.date_from, query.date_to


# --- Weekly queries ----------------------------------------------------------
def test_next_week_returns_all_records_in_order(repo, cache):
    reply = ask('What exams are scheduled next week?', repo, cache)
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 18), date(2026, 10, 22))
    assert ids_in(reply.text) == [4, 10, 5, 6]
    assert reply.outcome == 'answered'
    assert 'Sunday, 18 October 2026 – Thursday, 22 October 2026' in reply.text


@pytest.mark.parametrize('at,bounds', [
    ('2026-10-11T09:00', (date(2026, 10, 18), date(2026, 10, 22))),   # Sunday
    ('2026-10-12T09:00', (date(2026, 10, 18), date(2026, 10, 22))),   # Monday
    ('2026-10-15T09:00', (date(2026, 10, 18), date(2026, 10, 22))),   # Thursday
    ('2026-10-16T09:00', (date(2026, 10, 18), date(2026, 10, 22))),   # Friday
    ('2026-10-17T09:00', (date(2026, 10, 18), date(2026, 10, 22))),   # Saturday
    ('2026-12-30T09:00', (date(2027, 1, 3), date(2027, 1, 7))),       # year end
    ('2028-02-24T09:00', (date(2028, 2, 27), date(2028, 3, 2))),      # leap February
])
def test_next_week_bounds_by_weekday(at, bounds, repo, cache):
    ask("Give me next week's exam updates", repo, cache, at=at)
    assert date_bounds(repo.queries[0]) == bounds


def test_this_week_remaining_on_tuesday(repo, cache):
    reply = ask('What exams are left this week?', repo, cache)
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 13), date(2026, 10, 15))
    assert ids_in(reply.text) == [1, 2, 3]
    assert '(today)' in reply.text


def test_this_week_on_sunday_covers_whole_week(repo, cache):
    ask('What exams do we have this week?', repo, cache, at='2026-10-11T09:00')
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 11), date(2026, 10, 15))


@pytest.mark.parametrize('at', ['2026-10-16T09:00', '2026-10-17T22:00'])
def test_this_week_on_weekend_explains_and_offers_next_week(at, repo, cache):
    reply = ask('What exams do we have this week?', repo, cache, at=at)
    assert 'already over' in reply.text
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 18), date(2026, 10, 22))
    assert ids_in(reply.text) == [4, 10, 5, 6]


def test_timezone_boundary_thursday_night_vs_friday(repo, cache):
    # 23:59 Thursday in Dhaka is still Thursday even though UTC says 17:59.
    reply = ask('What exams are left this week?', repo, cache, at='2026-10-15T23:59')
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 15), date(2026, 10, 15))
    assert ids_in(reply.text) == [3]


def test_tomorrow(repo, cache):
    reply = ask('What is happening tomorrow?', repo, cache)
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 14), date(2026, 10, 14))
    assert ids_in(reply.text) == [2]


def test_sunday_to_thursday_range(repo, cache):
    reply = ask('What exams are scheduled from Sunday to Thursday?', repo, cache)
    assert date_bounds(repo.queries[0]) == (date(2026, 10, 11), date(2026, 10, 15))
    assert ids_in(reply.text) == [1, 2, 3]


def test_empty_range_is_honest_and_points_to_next(repo, cache):
    reply = ask('exams on 2026-10-17', repo, cache)
    assert reply.outcome == 'empty'
    assert 'No exam information has been posted for Saturday, 17 October 2026' in reply.text
    assert 'The next one posted is CSE-305 CT 1 on Sunday, 18 October 2026' in reply.text


def test_no_records_at_all(cache):
    reply = ask('What exams are scheduled next week?', FakeRepo([]), cache)
    assert reply.outcome == 'empty'
    assert 'No exam information has been posted for next week' in reply.text
    assert 'next one' not in reply.text


# --- Course / field resolution ------------------------------------------------
def test_next_database_ct_uses_exam_type_to_disambiguate(repo, cache):
    reply = ask('What is the next Database CT?', repo, cache)
    q = repo.queries[0]
    assert q.course_ids == (4,)
    assert set(q.exam_types) == {'CT 1', 'CT 2', 'CT 3'}
    assert ids_in(reply.text) == [4]


def test_ambiguous_course_asks_for_clarification(repo, cache):
    reply = ask('When is the next database exam?', repo, cache)
    assert reply.outcome == 'clarify'
    assert 'CSE-305' in reply.text and 'CSE-306' in reply.text
    assert repo.queries == []          # never guessed


@pytest.mark.parametrize('message', [
    'next exam of Human Computer Interface',
    'next exam of CSE-415',
    'next cse 415 exam',
    'next HCI exam',
])
def test_same_course_by_title_code_and_abbreviation(message, repo, cache):
    reply = ask(message, repo, cache, at='2026-10-13T12:00')  # after today's 09:00 CT
    assert repo.queries[0].course_ids == (1,)
    assert ids_in(reply.text) == [7]


def test_next_exam_skips_today_exam_already_started(repo, cache):
    before = ask('next exam', repo, cache, at='2026-10-13T08:00')
    after = ask('next exam', FakeRepo(list(ROWS)), cache, at='2026-10-13T09:30')
    assert ids_in(before.text) == [1]
    assert ids_in(after.text) == [2]


def test_next_returns_all_ties_on_same_day(repo, cache):
    reply = ask('next exam', repo, cache, at='2026-10-16T09:00')
    assert ids_in(reply.text) == [4, 10]


def test_syllabus_only_selects_only_needed_fields(repo, cache):
    reply = ask('syllabus of DBMS CT 1', repo, cache)
    q = repo.queries[0]
    assert 'syllabus' in q.select and 'venue' not in q.select and 'notes_link' not in q.select
    assert 'ER model\nNormalization' in reply.text      # line breaks preserved
    assert 'Room 302' not in reply.text


def test_date_and_syllabus(repo, cache):
    reply = ask('When is the next DBMS exam and what is its syllabus?', repo, cache)
    assert 'Sunday, 18 October 2026 · 9:00 AM' in reply.text
    assert 'ER model' in reply.text


def test_missing_syllabus_is_stated(repo, cache):
    reply = ask('syllabus for CSE 427 CT 1', repo, cache)
    assert 'Syllabus: not posted yet' in reply.text


def test_venue_when_present(repo, cache):
    reply = ask('where is the DBMS CT 1?', repo, cache)
    assert 'Venue: Room 302' in reply.text


def test_teacher_filter(repo, cache):
    reply = ask('next exam of Nafisa madam', repo, cache)
    assert repo.queries[0].faculty_ids == (4,)
    assert ids_in(reply.text) == [3]


def test_ambiguous_teacher(repo, cache):
    reply = ask('next exam of Shahriar sir', repo, cache)
    assert reply.outcome == 'clarify'
    assert 'Shahriar Kabir' in reply.text and 'Shahriar Sazzad' in reply.text


def test_unknown_course_is_not_invented(repo, cache):
    reply = ask('next exam of CSE-999', repo, cache)
    assert reply.outcome == 'unknown'
    assert "couldn't find a course" in reply.text
    assert repo.queries == []


def test_section_filter_includes_whole_class_rows(repo, cache):
    ask('next week exams for section A', repo, cache)
    assert repo.queries[0].section == 'A'
    rows = FakeRepo(list(ROWS)).query_exams(repo.queries[0])
    assert [r['id'] for r in rows] == [4, 10, 5]   # B-only exam (6) excluded; NULL-section rows kept


def test_theory_course_sections_in_answers(cache):
    rows = [exam_row(1, 1, 'CT 1', '2026-10-18', course_section='A', syllabus='Ch 1'),
            exam_row(2, 1, 'CT 1', '2026-10-18', course_section='B', syllabus='Ch 4'),
            exam_row(3, 2, 'CT 1', '2026-10-19')]
    reply = ask('next week exams for section A', FakeRepo(rows), cache)
    assert '🗓 2 exams' in reply.text   # Section B's CT excluded; both-sections exam kept
    assert 'CSE-415 · Human Computer Interface\n📝 CT 1 · Course Section A' in reply.text and 'Ch 4' not in reply.text
    assert '👤 Faculty: Nazmul Hasan' in reply.text   # CSE-415 Section A teacher
    assert 'CSE-427 · Digital Image Processing\n📝 CT 1 · Course Sections A & B' in reply.text
    assert 'Course Section A: Fairooz Tasnia · Course Section B: Shahriar Sazzad' in reply.text

    # A teacher's exams: only the section they take (Fairooz: CSE-415 B, CSE-427 A).
    reply = ask('next exam of Fairooz madam', FakeRepo(rows), cache)
    assert '📝 CT 1 · Course Section B' in reply.text and 'Ch 4' in reply.text and 'Ch 1' not in reply.text


def test_all_upcoming_for_a_course(repo, cache):
    reply = ask('Give me all upcoming exams of CSE-415', repo, cache, at='2026-10-13T12:00')
    assert ids_in(reply.text) == [7]
    reply = ask('Give me all upcoming exams of CSE-305', FakeRepo(list(ROWS)), cache)
    assert ids_in(reply.text) == [4, 8]


def test_no_time_given_falls_back_to_most_recent_past(cache):
    rows = [exam_row(9, 1, 'CT 1', '2026-10-04', syllabus='Intro')]
    reply = ask('HCI CT 1 syllabus', FakeRepo(rows), cache)
    assert 'Most recent' in reply.text and 'Intro' in reply.text


# --- Configuration changes are picked up -------------------------------------
def test_new_course_visible_after_cache_invalidation(repo):
    courses = [dict(c) for c in __import__('conftest').COURSES]
    state = {'courses': courses}
    cache = CatalogCache(loader=lambda class_id: make_catalog(state['courses']), ttl=3600)
    assert ask('next exam of Compiler Design', repo, cache).outcome == 'unknown'
    state['courses'] = courses + [{'id': 7, 'code': 'CSE-433', 'title': 'Compiler Design', 'course_type': 'Theoretical',
                                   'aliases': [], 'faculty': []}]
    cache.invalidate()
    reply = ask('next exam of Compiler Design', repo, cache)
    assert reply.outcome == 'empty'
    assert repo.queries[-1].course_ids == (7,)


# --- Failures ----------------------------------------------------------------
class FailingRepo:
    def query_exams(self, query):
        raise db_fetch.DatabaseError('down', code='unavailable')


def test_database_failure_is_not_reported_as_no_exams(cache):
    reply = ask('What exams are scheduled next week?', FailingRepo(), cache)
    assert reply.outcome == 'db_error'
    assert reply.text == DB_ERROR_TEXT
    assert 'No exam' not in reply.text


def test_catalog_failure_is_db_error():
    def loader(class_id):
        raise db_fetch.DatabaseError('down', code='unavailable')
    reply = ask('next exam', FakeRepo([]), CatalogCache(loader=loader))
    assert reply.outcome == 'db_error'


# --- Many records: nothing dropped -------------------------------------------
def test_long_week_is_split_without_losing_records(cache):
    rows = [exam_row(100 + i, 1 + i % 6, 'CT 1' if (1 + i % 6) in (1, 2, 4, 6) else 'Lab Test',
                     f'2026-10-{18 + i % 5:02d}', f'{8 + i % 8:02d}:00:00', syllabus='x' * 150)
            for i in range(40)]
    reply = ask('What exams are scheduled next week?', FakeRepo(rows), cache)
    assert len(reply.messages) > 1
    assert all(len(m) <= 2000 for m in reply.messages)
    assert sorted(ids_in(reply.text, rows)) == sorted(r['id'] for r in rows)


def test_plan_uses_single_query_for_ranges(repo, catalog):
    intent = Intent(time=TimeScope('next_week'), exam_types=['CT 1', 'CT 2'], course_mentions=['CSE-305'])
    plan = plan_query(intent, '', catalog, clock_at(TUESDAY)())
    execute(plan, repo, clock_at(TUESDAY)())
    assert len(repo.queries) == 1
    q = repo.queries[0]
    assert (q.course_ids, q.exam_types, q.date_from, q.date_to) == ((4,), ('CT 1', 'CT 2'), date(2026, 10, 18), date(2026, 10, 22))


def test_exam_type_keyword_is_matched(repo, cache):
    ask('When is the next DBMS CT 2?', repo, cache)
    assert repo.queries[0].exam_types == ('CT 2',)


def test_every_query_is_scoped_to_the_class(repo, cache):
    ask('What exams are scheduled next week?', repo, cache)
    ask('next exam of CSE-415', repo, cache)
    ask('exams on 2026-10-17', repo, cache)
    assert repo.queries and all(q.class_id == CLASS_ID for q in repo.queries)


def test_other_class_rows_are_never_shown(cache):
    other = {**exam_row(90, 1, 'CT 3', '2026-10-19', syllabus='Other class only'), 'class_id': 2}
    reply = ask('What exams are scheduled next week?', FakeRepo([other]), cache)
    assert reply.outcome == 'empty' and 'Other class only' not in reply.text
