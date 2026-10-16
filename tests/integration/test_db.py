"""Integration tests against the real migrations in an isolated Postgres + PostgREST.

Start the stack first (never points at Supabase):
    docker compose -f tests/db/docker-compose.yml up -d --wait
Skipped automatically when it is not running.

Each test gets its own class (as if from its own Discord channel), a random course
prefix and a far-future week, so tests don't interfere and can be re-run against
the same container.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import random
import string
import uuid
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

import db_fetch
import links
from Chatbot.Chatbot import answer
from Chatbot.catalog import CatalogCache
from test_academic import CODE_VECTORS
from conftest import clock_at

REST = 'http://localhost:54321'
JWT_SECRET = b'aicr-local-test-jwt-secret-0123456789abcdef'


def _jwt(role: str) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    header = b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
    payload = b64(json.dumps({'role': role, 'exp': 4102444800}).encode())
    sig = b64(hmac.new(JWT_SECRET, f'{header}.{payload}'.encode(), hashlib.sha256).digest())
    return f'{header}.{payload}.{sig}'


def _reachable() -> bool:
    try:
        urlopen(REST, timeout=2).read()
        return True
    except (URLError, OSError):
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason='test PostgREST not running (see tests/db/docker-compose.yml)')


STATE: dict[str, int] = {}


def snowflake() -> str:
    return str(random.randint(10 ** 17, 10 ** 18 - 1))


def new_class(name: str = 'Test class') -> dict:
    return db_fetch.create_class(name=name, guild_id=snowflake(), channel_id=snowflake(), cr_role_id=None)


def CID() -> int:
    """The current test's class."""
    return STATE['class_id']


@pytest.fixture(autouse=True)
def local_db(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', REST)
    monkeypatch.setenv('SUPABASE_API_KEY', _jwt('service_role'))
    STATE['class_id'] = new_class()['id']


def raw(method, path, role, body=None):
    """Direct PostgREST request as anon/authenticated, bypassing the backend."""
    token = _jwt(role)
    req = Request(f'{REST}/{path}', data=None if body is None else json.dumps(body).encode(), method=method,
                  headers={'Authorization': f'Bearer {token}', 'apikey': token, 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except HTTPError as error:
        return error.code, error.read().decode()


def prefix() -> str:
    return ''.join(random.choices(string.ascii_uppercase, k=4))


def faculty(n: int) -> list[int]:
    tag = uuid.uuid4().hex[:6]
    return [db_fetch.create_faculty(CID(), f'Teacher {tag} {i}')['id'] for i in range(n)]


def default_sections(code: str, faculty_ids: list[int]) -> dict[str, int]:
    """Theoretical codes (odd last digit): Section A = first teacher, Section B = last."""
    if not code[-1].isdigit() or int(code[-1]) % 2 == 0 or not faculty_ids:
        return {}
    return {'A': faculty_ids[0], 'B': faculty_ids[-1]}


def course(code: str, title: str, faculty_ids: list[int], aliases=(), sections=None) -> int:
    return db_fetch.save_course(class_id=CID(), course_id=None, code=code, title=title, aliases=list(aliases), faculty_ids=faculty_ids,
                                section_faculty=default_sections(code, faculty_ids) if sections is None else sections)


def exam(course_id, exam_type, day, *, time=None, section=None, course_section=None, syllabus=None, faculty_ids=(),
         request_id=None, exam_id=None):
    return db_fetch.save_exam(class_id=CID(), exam_id=exam_id, course_id=course_id, exam_type=exam_type, exam_date=day, exam_time=time,
                              section=section, course_section=course_section, syllabus=syllabus, venue=None, remarks=None,
                              notes_link=None, faculty_ids=list(faculty_ids), client_request_id=request_id, actor=None)


def far_week(offset_weeks: int) -> date:
    """A Sunday far in the future, unique per test."""
    base = date(2031, 1, 5)  # Sunday
    return base + timedelta(weeks=offset_weeks)


# --- Rules parity --------------------------------------------------------------
@pytest.mark.parametrize('raw_code,code,course_type', CODE_VECTORS)
def test_sql_code_rules_match_python(raw_code, code, course_type):
    assert db_fetch.rpc('normalize_course_code', {'p_code': raw_code}) == code
    if code:
        assert db_fetch.rpc('course_type_for_code', {'p_code': code}) == course_type


# --- Legacy backfill -------------------------------------------------------------
def test_legacy_backfill():
    rows = db_fetch.query_exams(db_fetch.ExamQuery(date_from=date(2026, 8, 1), date_to=date(2026, 8, 31), limit=50))
    legacy = {r['legacy_exam_id']: r for r in rows if r['legacy_exam_id']}
    assert set(legacy) == {1, 3, 4, 5, 6, 7}
    assert legacy[1]['exam_type'] == 'CT 2' and legacy[1]['course_code'] == 'CSE-415'
    assert legacy[3]['course_code'] == 'GEEM-433' and legacy[3]['exam_type'] == 'Mid'
    assert legacy[4]['section'] is None and legacy[4]['faculty_names'] == ['Nafisa Maliyat']
    assert legacy[4]['faculty_source'] == 'legacy'
    # Theoretical exams are whole-class: the rules migration cleared their legacy sections.
    assert all(r['section'] is None for r in legacy.values() if r['course_type'] == 'Theoretical')
    # The migration put the pre-Discord data in one class that no channel has claimed yet.
    legacy_class = db_fetch.fetch_unlinked_classes()[0]['id']
    sdp = next(c for c in db_fetch.fetch_active_courses(legacy_class) if c['code'] == 'CSE-464')
    assert sdp['title'] == 'Software Development Project-2' or 'Software Development Project-2' in sdp['aliases']
    assert sdp['course_type'] == 'Sessional'


# --- Direct access is blocked ---------------------------------------------------
@pytest.mark.parametrize('role', ['anon', 'authenticated'])
@pytest.mark.parametrize('method,path,body', [
    ('GET', 'exams', None),
    ('GET', 'courses', None),
    ('GET', 'exam_details', None),
    ('GET', 'cr_members', None),
    ('GET', 'Exams', None),
    ('POST', 'courses', {'code': 'HACK-101', 'title': 'Hack'}),
    ('DELETE', 'exams?id=gt.0', None),
    ('GET', 'classes', None),
    ('GET', 'class_notifications', None),
    ('POST', 'rpc/cr_save_course', {'p_class_id': 1, 'p_course_id': None, 'p_code': 'HACK-101', 'p_title': 'Hack',
                                    'p_aliases': [], 'p_faculty_ids': [], 'p_section_faculty': {}}),
    ('POST', 'rpc/cr_remove_course', {'p_class_id': 1, 'p_course_id': 1}),
])
def test_public_roles_cannot_read_or_write(role, method, path, body):
    status, text = raw(method, path, role, body)
    assert status in (401, 403, 404), (status, text)


# --- Course rules in the database ----------------------------------------------
def test_course_type_derived_and_locked():
    p = prefix()
    theory = course(f'{p}-301', 'Theory', faculty(2))
    lab = course(f'{p}-302', 'Lab', faculty(3))
    assert db_fetch.fetch_course(theory)['course_type'] == 'Theoretical'
    assert db_fetch.fetch_course(lab)['course_type'] == 'Sessional'
    with pytest.raises(db_fetch.DatabaseError):
        db_fetch._rest('PATCH', 'courses', [('id', f'eq.{theory}')], {'course_type': 'Sessional'})


def test_db_enforces_course_sections_even_without_backend_validation():
    p = prefix()
    with pytest.raises(db_fetch.DatabaseError) as err:
        course(f'{p}-301A', 'Bad', faculty(2))
    assert err.value.code == 'invalid_course_code'
    one, two = faculty(2)
    for bad in ({}, {'A': one}, {'B': two}, {'A': one, 'C': two}):
        with pytest.raises(db_fetch.DatabaseError) as err:
            course(f'{p}-301', 'Theory', [one, two], sections=bad)
        assert err.value.code == 'faculty_sections', bad
    # One teacher may take both course sections; faculty_ids are ignored for Theoretical courses.
    cid = course(f'{p}-301', 'Theory', [two], sections={'A': one, 'B': one})
    saved = db_fetch.fetch_course(cid)
    assert [f['id'] for f in saved['faculty']] == [one]
    assert {s: f['id'] for s, f in saved['section_faculty'].items()} == {'A': one, 'B': one}
    # Re-assigning sections replaces the teachers.
    db_fetch.save_course(class_id=CID(), course_id=cid, code=f'{p}-301', title='Theory', aliases=[], faculty_ids=[],
                         section_faculty={'A': two, 'B': one})
    saved = db_fetch.fetch_course(cid)
    assert {s: f['id'] for s, f in saved['section_faculty'].items()} == {'A': two, 'B': one}
    # Sessional: any number of teachers, no course sections.
    with pytest.raises(db_fetch.DatabaseError) as err:
        course(f'{p}-302', 'Lab', [one], sections={'A': one})
    assert err.value.code == 'faculty_sections'
    for i, count in enumerate((0, 1, 2, 5)):
        cid = course(f'{p}-{304 + 2 * i}', 'Lab', faculty(count))
        assert db_fetch.fetch_course(cid)['section_faculty'] == {}


def test_duplicate_active_course_rejected_but_archived_code_reusable():
    p = prefix()
    fac = faculty(2)
    first = course(f'{p}-301', 'One', fac)
    with pytest.raises(db_fetch.DatabaseError) as err:
        course(f'{p.lower()} 301', 'Again', fac)
    assert err.value.code == 'duplicate'
    exam(first, 'CT 1', far_week(1))
    assert db_fetch.remove_course(CID(), first) == 'archived'
    assert course(f'{p}-301', 'Next term', fac)


def test_remove_course_keeps_history():
    p = prefix()
    used = course(f'{p}-301', 'Used', faculty(2))
    unused = course(f'{p}-303', 'Unused', faculty(2))
    exam_id = exam(used, 'CT 1', far_week(2), syllabus='kept')
    assert db_fetch.remove_course(CID(), used) == 'archived'
    assert db_fetch.remove_course(CID(), unused) == 'deleted'
    kept = db_fetch.get_exam(exam_id)
    assert kept['syllabus'] == 'kept' and kept['course_archived'] is True
    assert all(c['id'] != used for c in db_fetch.fetch_active_courses(CID()))


def test_code_change_that_flips_type_is_blocked_once_exams_exist():
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-301', 'Theory', fac)
    exam(cid, 'CT 1', far_week(3))
    with pytest.raises(db_fetch.DatabaseError) as err:
        db_fetch.save_course(class_id=CID(), course_id=cid, code=f'{p}-302', title='Theory', aliases=[], faculty_ids=fac,
                             section_faculty={})
    assert err.value.code == 'course_type_locked'
    # Same-type rename is fine
    db_fetch.save_course(class_id=CID(), course_id=cid, code=f'{p}-305', title='Renamed', aliases=[], faculty_ids=[],
                         section_faculty=default_sections(f'{p}-305', fac))
    assert db_fetch.fetch_course(cid)['code'] == f'{p}-305'


def test_faculty_removal_rules():
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-302', 'Lab', fac)
    with pytest.raises(db_fetch.DatabaseError) as err:
        db_fetch.remove_faculty(CID(), fac[0])
    assert err.value.code == 'in_use'
    exam(cid, 'Lab Test', far_week(4), faculty_ids=[fac[0]])
    db_fetch.remove_course(CID(), cid)
    assert db_fetch.remove_faculty(CID(), fac[0]) == 'archived'      # still referenced by history
    assert db_fetch.remove_faculty(CID(), faculty(1)[0]) == 'deleted'


# --- Exam rules in the database --------------------------------------------------
def test_exam_type_must_match_course_type_at_db_level():
    p = prefix()
    theory = course(f'{p}-301', 'Theory', faculty(2))
    lab = course(f'{p}-302', 'Lab', faculty(3))
    assert exam(theory, 'Mid', far_week(5))  # Mid is a regular Theoretical type now
    for cid, bad in ((theory, 'Lab Test'), (lab, 'CT 1'), (lab, 'Mid')):
        with pytest.raises(db_fetch.DatabaseError) as err:
            exam(cid, bad, far_week(5))
        assert err.value.code == 'invalid_exam_type'
    # Even a raw insert with the service key goes through the trigger
    with pytest.raises(db_fetch.DatabaseError):
        db_fetch._rest('POST', 'exams', payload={'course_id': lab, 'exam_type': 'CT 1', 'exam_date': '2031-02-02'})


def test_exam_faculty_must_belong_to_course():
    p = prefix()
    cid = course(f'{p}-302', 'Lab', faculty(2))
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(cid, 'Lab Test', far_week(6), faculty_ids=faculty(1))
    assert err.value.code == 'invalid_faculty'


def test_double_submit_creates_one_row_and_duplicates_are_rejected():
    p = prefix()
    cid = course(f'{p}-301', 'Theory', faculty(2))
    request_id = str(uuid.uuid4())
    first = exam(cid, 'CT 1', far_week(7), request_id=request_id)
    second = exam(cid, 'CT 1', far_week(7), request_id=request_id)
    assert first == second
    rows = db_fetch.query_exams(db_fetch.ExamQuery(course_ids=(cid,)))
    assert len(rows) == 1
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(cid, 'CT 1', far_week(7))  # new submission, same course/type/date/section
    assert err.value.code == 'duplicate'
    with pytest.raises(db_fetch.DatabaseError) as err:  # Theoretical: the class section is dropped, so still a duplicate
        exam(cid, 'CT 1', far_week(7), section='B')
    assert err.value.code == 'duplicate'
    with pytest.raises(db_fetch.DatabaseError) as err:  # Theoretical: one CT 1 per course section, whatever the date
        exam(cid, 'CT 1', far_week(7) + timedelta(days=3), course_section='A')
    assert err.value.code == 'duplicate'
    lab = course(f'{p}-302', 'Lab', faculty(1))
    assert exam(lab, 'Lab Test', far_week(7), section='A')
    assert exam(lab, 'Lab Test', far_week(7), section='B')  # Sessional: different section is fine
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(lab, 'Lab Test', far_week(7), section='a')
    assert err.value.code == 'duplicate'


def test_theoretical_exams_never_store_a_section():
    p = prefix()
    theory = course(f'{p}-301', 'Theory', faculty(2))
    via_rpc = exam(theory, 'CT 1', far_week(9), section='A')
    assert db_fetch.get_exam(via_rpc)['section'] is None
    # Even a raw insert with the service key goes through the trigger
    db_fetch._rest('POST', 'exams', payload={'course_id': theory, 'exam_type': 'CT 2', 'exam_date': '2031-03-09', 'section': 'C'})
    rows = db_fetch.query_exams(db_fetch.ExamQuery(course_ids=(theory,)))
    assert [r['section'] for r in rows] == [None, None]


def test_theory_course_sections_share_one_sitting():
    p = prefix()
    one, two = faculty(2)
    cid = course(f'{p}-301', 'Theory', [one, two], sections={'A': one, 'B': two})
    day = far_week(10)
    a = exam(cid, 'CT 1', day, time='09:00', course_section='a', syllabus='Ch 1', faculty_ids=[two])
    row_a = db_fetch.get_exam(a)
    assert row_a['course_section'] == 'A' and row_a['exam_faculty_ids'] == []   # picks are ignored
    assert row_a['faculty_ids'] == [one] and row_a['section_faculty'] == [{'section': 'A', 'name': row_a['faculty_names'][0]}]

    # Section B posted later for a different time: Section A follows (both sections sit together).
    b = exam(cid, 'CT 1', day + timedelta(days=1), time='10:00', course_section='B', syllabus='Ch 4')
    rows = {r['id']: r for r in db_fetch.query_exams(db_fetch.ExamQuery(course_ids=(cid,)))}
    assert {(r['exam_date'], r['exam_time']) for r in rows.values()} == {((day + timedelta(days=1)).isoformat(), '10:00:00')}
    assert rows[b]['faculty_ids'] == [two] and rows[a]['syllabus'] == 'Ch 1'

    # "Both sections" cannot coexist with a section's own record of the same exam.
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(cid, 'CT 1', day, course_section=None)
    assert err.value.code == 'duplicate'
    both = exam(cid, 'CT 2', day + timedelta(days=7))
    row = db_fetch.get_exam(both)
    assert row['course_section'] is None and sorted(row['faculty_ids']) == sorted([one, two])
    assert [i['section'] for i in row['section_faculty']] == ['A', 'B']

    # Student filters: a section sees its own record and both-sections records.
    section_a = db_fetch.query_exams(db_fetch.ExamQuery(course_ids=(cid,), section='A'))
    assert sorted(r['id'] for r in section_a) == sorted([a, both])

    # Sessional exams never store a course section, even via a raw insert.
    lab = course(f'{p}-302', 'Lab', [one])
    db_fetch._rest('POST', 'exams', payload={'course_id': lab, 'exam_type': 'Lab Test', 'exam_date': '2031-03-09',
                                             'course_section': 'A'})
    assert [r['course_section'] for r in db_fetch.query_exams(db_fetch.ExamQuery(course_ids=(lab,)))] == [None]


def test_edit_exam_and_faculty_selection():
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-302', 'Lab', fac)
    eid = exam(cid, 'Lab Test', far_week(8), syllabus='old', faculty_ids=[fac[0]])
    assert db_fetch.get_exam(eid)['faculty_source'] == 'exam'
    exam(cid, 'Evaluation', far_week(8) + timedelta(days=1), time='10:30', syllabus='line 1\nline 2', faculty_ids=[], exam_id=eid)
    row = db_fetch.get_exam(eid)
    assert (row['exam_type'], row['exam_time'], row['syllabus']) == ('Evaluation', '10:30:00', 'line 1\nline 2')
    assert row['faculty_source'] == 'course' and len(row['faculty_names']) == 2


# --- Student agent end to end through real PostgREST -----------------------------
def test_agent_weekly_and_filters_against_real_db():
    p = prefix()
    tag = ''.join(random.choices(string.ascii_lowercase, k=6))   # title word distinct from the code prefix
    fac = faculty(3)
    theory = course(f'{p}-301', f'Quantum Widgets {tag}', fac[:2])
    lab = course(f'{p}-302', f'Quantum Widgets {tag} Lab', fac)
    sunday = far_week(20)
    exam(theory, 'CT 1', sunday, time='09:00', syllabus='Ch 1\nCh 2')
    exam(lab, 'Lab Test', sunday + timedelta(days=2), time='14:00', section='A')
    exam(theory, 'CT 2', sunday + timedelta(days=4), course_section='B')
    exam(theory, 'CT 3', sunday + timedelta(days=7))               # following week: must not appear

    cache = CatalogCache(ttl=0)
    tuesday_before = (sunday - timedelta(days=5)).isoformat() + 'T10:00'

    reply = answer('What exams are scheduled next week?', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    text = reply.text
    ours = [line for line in text.splitlines() if f'{p}-30' in line]
    assert len(ours) == 3, text
    assert text.index('CT 1') < text.index('Lab Test') < text.index('CT 2')
    assert 'CT 3' not in text
    assert 'Ch 1\nCh 2' in text
    assert reply.metrics.db_calls == 3   # 2 catalog + 1 exam query

    # Both-sections / whole-class exams show for every section; sectioned ones only for theirs.
    section_a = answer('next week exams for section A', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    assert all(t in section_a.text for t in ('CT 1', 'Lab Test')), section_a.text
    ours = [block for block in section_a.text.split('\n\n') if f'{p}-301' in block]
    assert ours and not any('CT 2' in block for block in ours)   # CT 2 is Section B only
    section_b = answer(f'next week exams of {p}-302 for section B', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    assert 'Lab Test' not in section_b.text

    teacher = db_fetch.fetch_faculty(CID())
    second_name = next(f['name'] for f in teacher if f['id'] == fac[1])
    by_teacher = answer(f'next week exams of {second_name} sir', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    assert 'CT 2' in by_teacher.text and 'Lab Test' in by_teacher.text   # Lab: via course faculty; CT 2: Section B
    assert 'CT 2 · Course Section B' in by_teacher.text

    exact_title = answer(f'next quantum widgets {tag} exam', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    assert exact_title.outcome == 'answered' and 'Lab Test' not in exact_title.text   # exact title wins

    ambiguous = answer(f'next widgets {tag} exam', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    assert ambiguous.outcome == 'clarify'

    by_type = answer(f'next widgets {tag} CT', class_id=CID(), clock=clock_at(tuesday_before), cache=cache)
    assert by_type.outcome == 'answered' and 'CT 1' in by_type.text


def test_cr_api_write_then_agent_sees_it_immediately(monkeypatch):
    from fastapi.testclient import TestClient

    import auth
    import main
    from Chatbot.catalog import catalog_cache

    auth.clear_auth_cache()
    client = TestClient(main.app)
    headers = {'Authorization': f'Bearer {links.make_editor_token(CID(), "123456789012345678")}'}

    p = prefix()
    fac = [client.post('/api/faculty', headers=headers, json={'name': f'Dr {p} {i}'}).json()['id'] for i in range(2)]
    catalog_cache.get(CID())  # warm the cache before the course exists
    created = client.post('/api/courses', headers=headers,
                          json={'code': f'{p.lower()} 211', 'title': f'Applied Things {p}',
                                'section_faculty': {'A': fac[0], 'B': fac[0]}})
    assert created.status_code == 201, created.text
    cid = created.json()['id']

    body = {'course_id': cid, 'exam_type': 'CT 1', 'exam_date': far_week(30).isoformat(),
            'syllabus': 'Unit 1', 'client_request_id': str(uuid.uuid4())}
    r1 = client.post('/api/exams', headers=headers, json=body)
    r2 = client.post('/api/exams', headers=headers, json=body)      # double tap
    assert r1.status_code == r2.status_code == 201 and r1.json()['id'] == r2.json()['id']

    bad = client.post('/api/exams', headers=headers, json={**body, 'exam_type': 'Lab Test', 'client_request_id': str(uuid.uuid4())})
    assert bad.status_code == 422

    asked_on = (far_week(30) - timedelta(days=3)).isoformat() + 'T10:00'
    reply = answer(f'next applied things {p.lower()} exam', class_id=CID(), clock=clock_at(asked_on), cache=catalog_cache)
    assert reply.outcome == 'answered', reply.text
    assert f'{p}-211' in reply.text and 'Unit 1' in reply.text

    renamed = client.patch(f'/api/courses/{cid}', headers=headers,
                           json={'code': f'{p}-211', 'title': f'Renamed Things {p}',
                                 'section_faculty': {'A': fac[0], 'B': fac[1]}})
    assert renamed.status_code == 200
    reply = answer(f'next renamed things {p.lower()} exam', class_id=CID(), clock=clock_at(asked_on), cache=catalog_cache)
    assert f'Renamed Things {p}' in reply.text

    listed = client.get('/api/exams', headers=headers, params={'course_id': cid})
    assert listed.status_code == 200 and len(listed.json()['exams']) == 1
    assert client.delete(f'/api/exams/{r1.json()["id"]}', headers=headers).json() == {'result': 'deleted'}
    assert client.delete(f'/api/exams/{r1.json()["id"]}', headers=headers).status_code == 404


# --- Classes (one per Discord channel) ----------------------------------------------
def test_classes_are_isolated_in_the_database():
    mine = CID()
    other = new_class('Other class')['id']
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-301', 'Theory', fac)
    exam_id = exam(cid, 'CT 1', far_week(40), syllabus='mine')

    # The same course code and teacher name may exist in another class.
    STATE['class_id'] = other
    other_fac = faculty(2)
    assert course(f'{p}-301', 'Theory', other_fac)
    assert db_fetch.create_faculty(other, db_fetch.fetch_faculty(mine)[0]['name'])

    # Another class's course, teacher or exam can't be used, changed or removed from this class.
    with pytest.raises(db_fetch.DatabaseError) as err:
        course(f'{p}-303', 'Theory', fac)                       # teachers of the first class
    assert err.value.code == 'unknown_faculty'
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(cid, 'CT 2', far_week(40))                         # the first class's course
    assert err.value.code == 'invalid_course'
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(cid, 'CT 1', far_week(41), exam_id=exam_id)        # the first class's exam
    assert err.value.code == 'not_found'
    with pytest.raises(db_fetch.DatabaseError) as err:
        db_fetch.save_course(class_id=other, course_id=cid, code=f'{p}-301', title='Hijack', aliases=[],
                             faculty_ids=[], section_faculty={'A': other_fac[0], 'B': other_fac[1]})
    assert err.value.code == 'not_found'
    for remove, target in ((db_fetch.remove_course, cid), (db_fetch.remove_faculty, fac[0])):
        with pytest.raises(db_fetch.DatabaseError) as err:
            remove(other, target)
        assert err.value.code == 'not_found'
    # Even a raw link with the service key goes through the trigger.
    with pytest.raises(db_fetch.DatabaseError):
        db_fetch._rest('POST', 'course_faculty', payload={'course_id': cid, 'faculty_id': other_fac[0]})

    assert db_fetch.get_exam(exam_id)['syllabus'] == 'mine' and db_fetch.get_exam(exam_id)['class_id'] == mine
    assert [r['id'] for r in db_fetch.query_exams(db_fetch.ExamQuery(class_id=other))] == []
    assert [r['id'] for r in db_fetch.query_exams(db_fetch.ExamQuery(class_id=mine))] == [exam_id]
    assert {c['code'] for c in db_fetch.fetch_active_courses(other)} == {f'{p}-301'}


def test_class_lookup_and_settings():
    created = new_class('Lookup class')
    assert db_fetch.fetch_class_by_channel(created['discord_channel_id'])['id'] == created['id']
    assert db_fetch.fetch_class_by_view_key(created['view_key'])['id'] == created['id']
    assert created['auto_updates'] is True
    with pytest.raises(db_fetch.DatabaseError) as err:   # one class per channel
        db_fetch.create_class(name='Again', guild_id=snowflake(), channel_id=created['discord_channel_id'], cr_role_id=None)
    assert err.value.code == 'duplicate'
    updated = db_fetch.update_class(created['id'], {'auto_updates': False, 'name': 'Renamed'})
    assert updated['name'] == 'Renamed' and created['id'] not in {c['id'] for c in db_fetch.fetch_scheduled_classes()}
    # Linking only succeeds for a class without a channel.
    assert db_fetch.update_class(created['id'], {'discord_channel_id': snowflake()}, only_if_unlinked=True) is None


def test_notification_is_claimed_once():
    key = f'weekly:{uuid.uuid4().hex[:8]}'
    assert db_fetch.claim_notification(CID(), key) is True
    assert db_fetch.claim_notification(CID(), key) is False
    db_fetch.release_notification(CID(), key)
    assert db_fetch.claim_notification(CID(), key) is True
    db_fetch.finish_notification(CID(), key, 'sent', '2 exam(s)')
    assert db_fetch.claim_notification(CID(), key) is False


def test_updates_against_real_db():
    import updates

    p = prefix()
    cid = course(f'{p}-301', 'Graph Things', faculty(2))
    sunday = far_week(45)
    exam(cid, 'CT 1', sunday + timedelta(days=1), time='09:00', syllabus='Trees')
    exam(cid, 'CT 2', sunday + timedelta(days=1), time='13:00', course_section='A')
    friday_before = clock_at((sunday - timedelta(days=2)).isoformat() + 'T18:00')()
    week = updates.week_update(CID(), 'next', friday_before)
    assert week.exam_count == 2 and 'Trees' in week.messages[0]
    day = updates.next_exam_day_update(CID(), friday_before)
    assert day.exam_count == 2 and '9:00 AM' in day.messages[0] and '1:00 PM' in day.messages[0]
    assert updates.reminder_update(CID(), sunday + timedelta(days=1)).exam_count == 2
