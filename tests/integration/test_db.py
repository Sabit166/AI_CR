"""Integration tests against the real migrations in an isolated Postgres + PostgREST.

Start the stack first (never points at Supabase):
    docker compose -f tests/db/docker-compose.yml up -d --wait
Skipped automatically when it is not running.

Each test uses its own random course prefix and a far-future week, so tests
don't interfere and can be re-run against the same container.
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


@pytest.fixture(autouse=True)
def local_db(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', REST)
    monkeypatch.setenv('SUPABASE_API_KEY', _jwt('service_role'))


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
    return [db_fetch.create_faculty(f'Teacher {tag} {i}')['id'] for i in range(n)]


def course(code: str, title: str, faculty_ids: list[int], aliases=(), note=None) -> int:
    return db_fetch.save_course(course_id=None, code=code, title=title, aliases=list(aliases),
                                faculty_ids=faculty_ids, faculty_exception_note=note)


def exam(course_id, exam_type, day, *, time=None, section=None, syllabus=None, faculty_ids=(), request_id=None, exam_id=None):
    return db_fetch.save_exam(exam_id=exam_id, course_id=course_id, exam_type=exam_type, exam_date=day, exam_time=time,
                              section=section, syllabus=syllabus, venue=None, remarks=None, notes_link=None,
                              faculty_ids=list(faculty_ids), client_request_id=request_id, user_id=None)


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
    sdp = next(c for c in db_fetch.fetch_active_courses() if c['code'] == 'CSE-464')
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
    ('POST', 'rpc/cr_save_course', {'p_course_id': None, 'p_code': 'HACK-101', 'p_title': 'Hack', 'p_aliases': [],
                                    'p_faculty_ids': [], 'p_faculty_exception_note': 'x' * 5}),
    ('POST', 'rpc/cr_remove_course', {'p_course_id': 1}),
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


def test_db_rejects_bad_codes_and_counts_even_without_backend_validation():
    p = prefix()
    with pytest.raises(db_fetch.DatabaseError) as err:
        course(f'{p}-301A', 'Bad', faculty(2))
    assert err.value.code == 'invalid_course_code'
    for count in (0, 1, 3):
        with pytest.raises(db_fetch.DatabaseError) as err:
            course(f'{p}-301', 'Theory', faculty(count))
        assert err.value.code == 'faculty_count'
    with pytest.raises(db_fetch.DatabaseError) as err:  # no exception-note override any more
        course(f'{p}-301', 'With note', faculty(1), note='Single teacher this term')
    assert err.value.code == 'faculty_count'
    # Sessional: any number of teachers
    for i, count in enumerate((0, 1, 2, 5)):
        cid = course(f'{p}-{302 + 2 * i}', 'Lab', faculty(count), note='ignored')
        assert db_fetch.fetch_course(cid)['faculty_exception_note'] is None


def test_duplicate_active_course_rejected_but_archived_code_reusable():
    p = prefix()
    fac = faculty(2)
    first = course(f'{p}-301', 'One', fac)
    with pytest.raises(db_fetch.DatabaseError) as err:
        course(f'{p.lower()} 301', 'Again', fac)
    assert err.value.code == 'duplicate'
    exam(first, 'CT 1', far_week(1))
    assert db_fetch.remove_course(first) == 'archived'
    assert course(f'{p}-301', 'Next term', fac)


def test_remove_course_keeps_history():
    p = prefix()
    used = course(f'{p}-301', 'Used', faculty(2))
    unused = course(f'{p}-303', 'Unused', faculty(2))
    exam_id = exam(used, 'CT 1', far_week(2), syllabus='kept')
    assert db_fetch.remove_course(used) == 'archived'
    assert db_fetch.remove_course(unused) == 'deleted'
    kept = db_fetch.get_exam(exam_id)
    assert kept['syllabus'] == 'kept' and kept['course_archived'] is True
    assert all(c['id'] != used for c in db_fetch.fetch_active_courses())


def test_code_change_that_flips_type_is_blocked_once_exams_exist():
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-301', 'Theory', fac)
    exam(cid, 'CT 1', far_week(3))
    with pytest.raises(db_fetch.DatabaseError) as err:
        db_fetch.save_course(course_id=cid, code=f'{p}-302', title='Theory', aliases=[], faculty_ids=fac,
                             faculty_exception_note='renamed')
    assert err.value.code == 'course_type_locked'
    # Same-type rename is fine
    db_fetch.save_course(course_id=cid, code=f'{p}-305', title='Renamed', aliases=[], faculty_ids=fac, faculty_exception_note=None)
    assert db_fetch.fetch_course(cid)['code'] == f'{p}-305'


def test_faculty_removal_rules():
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-301', 'Theory', fac)
    with pytest.raises(db_fetch.DatabaseError) as err:
        db_fetch.remove_faculty(fac[0])
    assert err.value.code == 'in_use'
    exam(cid, 'CT 1', far_week(4), faculty_ids=[fac[0]])
    db_fetch.remove_course(cid)
    assert db_fetch.remove_faculty(fac[0]) == 'archived'      # still referenced by history
    assert db_fetch.remove_faculty(faculty(1)[0]) == 'deleted'


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
    cid = course(f'{p}-301', 'Theory', faculty(2))
    with pytest.raises(db_fetch.DatabaseError) as err:
        exam(cid, 'CT 1', far_week(6), faculty_ids=faculty(1))
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
    with pytest.raises(db_fetch.DatabaseError) as err:  # Theoretical: the section is dropped, so still a duplicate
        exam(cid, 'CT 1', far_week(7), section='B')
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


def test_edit_exam_and_faculty_selection():
    p = prefix()
    fac = faculty(2)
    cid = course(f'{p}-301', 'Theory', fac)
    eid = exam(cid, 'CT 1', far_week(8), syllabus='old', faculty_ids=[fac[0]])
    assert db_fetch.get_exam(eid)['faculty_source'] == 'exam'
    exam(cid, 'CT 2', far_week(8) + timedelta(days=1), time='10:30', syllabus='line 1\nline 2', faculty_ids=[], exam_id=eid)
    row = db_fetch.get_exam(eid)
    assert (row['exam_type'], row['exam_time'], row['syllabus']) == ('CT 2', '10:30:00', 'line 1\nline 2')
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
    exam(theory, 'CT 2', sunday + timedelta(days=4), faculty_ids=[fac[1]])
    exam(theory, 'CT 3', sunday + timedelta(days=7))               # following week: must not appear

    cache = CatalogCache(ttl=0)
    tuesday_before = (sunday - timedelta(days=5)).isoformat() + 'T10:00'

    reply = answer('What exams are scheduled next week?', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    text = reply.text
    ours = [line for line in text.splitlines() if f'{p}-30' in line]
    assert len(ours) == 3, text
    assert text.index('CT 1') < text.index('Lab Test') < text.index('CT 2')
    assert 'CT 3' not in text
    assert 'Ch 1\nCh 2' in text
    assert reply.metrics.llm_calls == 0 and reply.metrics.db_calls == 3   # 2 catalog + 1 exam query

    # Whole-class (Theoretical) exams show for every section; sectioned Sessional ones only for theirs.
    section_a = answer('next week exams for section A', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    assert all(t in section_a.text for t in ('CT 1', 'Lab Test', 'CT 2')), section_a.text
    section_b = answer(f'next week exams of {p}-302 for section B', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    assert 'Lab Test' not in section_b.text

    teacher = db_fetch.fetch_faculty()
    second_name = next(f['name'] for f in teacher if f['id'] == fac[1])
    by_teacher = answer(f'next week exams of {second_name} sir', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    assert 'CT 2' in by_teacher.text and 'Lab Test' in by_teacher.text   # Lab: via course faculty; CT 2: picked

    exact_title = answer(f'next quantum widgets {tag} exam', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    assert exact_title.outcome == 'answered' and 'Lab Test' not in exact_title.text   # exact title wins

    ambiguous = answer(f'next widgets {tag} exam', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    assert ambiguous.outcome == 'clarify'

    by_type = answer(f'next widgets {tag} CT', clock=clock_at(tuesday_before), cache=cache, use_llm=False)
    assert by_type.outcome == 'answered' and 'CT 1' in by_type.text


def test_cr_api_write_then_agent_sees_it_immediately(monkeypatch):
    from fastapi.testclient import TestClient

    import auth
    import main
    from Chatbot.catalog import catalog_cache

    auth.clear_auth_cache()
    monkeypatch.setattr(db_fetch, 'fetch_auth_user', lambda token: {'id': '33333333-3333-3333-3333-333333333333'})
    monkeypatch.setattr(db_fetch, 'is_cr_member', lambda uid: True)
    client = TestClient(main.app)
    headers = {'Authorization': 'Bearer t'}

    p = prefix()
    fac = [client.post('/api/faculty', headers=headers, json={'name': f'Dr {p} {i}'}).json()['id'] for i in range(2)]
    catalog_cache.get()  # warm the cache before the course exists
    created = client.post('/api/courses', headers=headers,
                          json={'code': f'{p.lower()} 211', 'title': f'Applied Things {p}', 'faculty_ids': fac})
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
    reply = answer(f'next applied things {p.lower()} exam', clock=clock_at(asked_on), cache=catalog_cache, use_llm=False)
    assert reply.outcome == 'answered', reply.text
    assert f'{p}-211' in reply.text and 'Unit 1' in reply.text

    renamed = client.patch(f'/api/courses/{cid}', headers=headers,
                           json={'code': f'{p}-211', 'title': f'Renamed Things {p}', 'faculty_ids': fac})
    assert renamed.status_code == 200
    reply = answer(f'next renamed things {p.lower()} exam', clock=clock_at(asked_on), cache=catalog_cache, use_llm=False)
    assert f'Renamed Things {p}' in reply.text

    listed = client.get('/api/exams', headers=headers, params={'course_id': cid})
    assert listed.status_code == 200 and len(listed.json()['exams']) == 1
    assert client.delete(f'/api/exams/{r1.json()["id"]}', headers=headers).json() == {'result': 'deleted'}
    assert client.delete(f'/api/exams/{r1.json()["id"]}', headers=headers).status_code == 404
