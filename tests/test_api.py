"""CR API: authorization and server-side validation (database layer stubbed).
tests/integration/test_db.py runs the same writes against real Postgres."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import auth
import db_fetch
import main
from conftest import COURSES, EXAM_TYPES, exam_row

CR_TOKEN = 'cr-token'
STUDENT_TOKEN = 'student-token'
CR_ID = '11111111-1111-1111-1111-111111111111'
STUDENT_ID = '22222222-2222-2222-2222-222222222222'


@pytest.fixture
def client(monkeypatch):
    auth.clear_auth_cache()
    users = {CR_TOKEN: {'id': CR_ID, 'email': 'cr@example.com'},
             STUDENT_TOKEN: {'id': STUDENT_ID, 'email': 'student@example.com'}}
    monkeypatch.setattr(db_fetch, 'fetch_auth_user', lambda token: users.get(token))
    monkeypatch.setattr(db_fetch, 'is_cr_member', lambda user_id: user_id == CR_ID)
    monkeypatch.setattr(db_fetch, 'fetch_exam_types', lambda: EXAM_TYPES)
    courses = {c['id']: {**c, 'archived_at': None, 'faculty_exception_note': None} for c in COURSES}
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: courses.get(cid))
    writes = []
    monkeypatch.setattr(db_fetch, 'save_course', lambda **kw: writes.append(('course', kw)) or 99)
    monkeypatch.setattr(db_fetch, 'save_exam', lambda **kw: writes.append(('exam', kw)) or 500)
    monkeypatch.setattr(db_fetch, 'delete_exam', lambda exam_id: writes.append(('delete', exam_id)) or True)
    monkeypatch.setattr(db_fetch, 'remove_course', lambda cid: writes.append(('remove_course', cid)) or 'archived')
    monkeypatch.setattr(db_fetch, 'get_exam', lambda eid: exam_row(eid, 1, 'CT 1', '2026-10-20') if eid in (500, 7) else None)
    test_client = TestClient(main.app)
    test_client.writes = writes
    return test_client


def h(token):
    return {'Authorization': f'Bearer {token}'}


VALID_EXAM = {'course_id': 1, 'exam_type': 'CT 1', 'exam_date': '2026-10-20', 'exam_time': '09:00',
              'syllabus': 'Ch 1\nCh 2', 'faculty_ids': [1]}


# --- Authorization -------------------------------------------------------------
@pytest.mark.parametrize('method,path', [
    ('get', '/api/courses'), ('post', '/api/courses'), ('patch', '/api/courses/1'), ('delete', '/api/courses/1'),
    ('get', '/api/faculty'), ('post', '/api/faculty'), ('delete', '/api/faculty/1'),
    ('get', '/api/exams'), ('post', '/api/exams'), ('patch', '/api/exams/7'), ('delete', '/api/exams/7'),
    ('get', '/api/config'),
])
def test_requires_sign_in(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=h('forged')).status_code == 401


@pytest.mark.parametrize('method,path,body', [
    ('post', '/api/courses', {'code': 'CSE-101', 'title': 'X', 'faculty_ids': [1, 2]}),
    ('post', '/api/exams', VALID_EXAM),
    ('patch', '/api/exams/7', VALID_EXAM),
    ('delete', '/api/exams/7', None),
    ('delete', '/api/courses/1', None),
])
def test_signed_in_non_cr_is_forbidden(client, method, path, body):
    kwargs = {'headers': h(STUDENT_TOKEN)}
    if body is not None:
        kwargs['json'] = body
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert client.writes == []


def test_legacy_unauthenticated_exam_endpoints_are_gone(client):
    assert client.post('/exams', json={'Course Code': 'X'}).status_code in (404, 405)
    assert client.delete('/exams/1').status_code in (404, 405)


def test_auth_outage_is_503_not_access(client, monkeypatch):
    auth.clear_auth_cache()

    def down(token):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'fetch_auth_user', down)
    assert client.get('/api/courses', headers=h(CR_TOKEN)).status_code == 503


# --- Course validation ---------------------------------------------------------
def test_create_theoretical_course(client, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: {'id': cid, 'code': 'CSE-433'})
    r = client.post('/api/courses', headers=h(CR_TOKEN),
                    json={'code': 'cse 433', 'title': '  Compiler   Design ', 'aliases': ['CD', 'CD', ' '], 'faculty_ids': [1, 2]})
    assert r.status_code == 201, r.text
    kind, kw = client.writes[0]
    assert kw['code'] == 'CSE-433' and kw['title'] == 'Compiler Design' and kw['aliases'] == ['CD']
    assert kw['faculty_exception_note'] is None


@pytest.mark.parametrize('code', ['CSE-433A', '433', 'C-433', ''])
def test_invalid_course_code_rejected(client, code):
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={'code': code, 'title': 'X Y', 'faculty_ids': [1, 2]})
    assert r.status_code == 422
    assert r.json()['detail']['field'] == 'code'
    assert client.writes == []


@pytest.mark.parametrize('code,faculty,ok', [
    ('CSE-433', [1, 2], True), ('CSE-433', [1], False), ('CSE-433', [1, 2, 3], False),
    ('CSE-434', [1, 2, 3], True), ('CSE-434', [1, 2, 3, 4], True), ('CSE-434', [1, 2], False),
])
def test_faculty_count_rules(client, monkeypatch, code, faculty, ok):
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: {'id': cid})
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={'code': code, 'title': 'Course', 'faculty_ids': faculty})
    assert (r.status_code == 201) == ok, r.text
    if not ok:
        assert r.json()['detail']['can_override'] is True


def test_faculty_count_exception_with_note(client, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: {'id': cid})
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={
        'code': 'CSE-434', 'title': 'Course', 'faculty_ids': [1, 2], 'faculty_exception_note': 'Only two teachers this term'})
    assert r.status_code == 201
    assert client.writes[0][1]['faculty_exception_note'] == 'Only two teachers this term'


def test_duplicate_course_conflict(client, monkeypatch):
    def dup(**kw):
        raise db_fetch.DatabaseError('dup', code='duplicate', status=409)
    monkeypatch.setattr(db_fetch, 'save_course', dup)
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={'code': 'CSE-415', 'title': 'HCI', 'faculty_ids': [1, 2]})
    assert r.status_code == 409
    assert 'already configured' in r.json()['detail']['message']


def test_remove_course_reports_archive(client):
    r = client.delete('/api/courses/1', headers=h(CR_TOKEN))
    assert r.json() == {'result': 'archived'}


# --- Exam validation -----------------------------------------------------------
def test_create_exam(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'client_request_id': '3f1e4c1a-0000-4000-8000-000000000001'})
    assert r.status_code == 201, r.text
    _, kw = client.writes[0]
    assert kw['user_id'] == CR_ID and kw['client_request_id'] == '3f1e4c1a-0000-4000-8000-000000000001'
    assert kw['syllabus'] == 'Ch 1\nCh 2'


@pytest.mark.parametrize('course_id,exam_type', [
    (1, 'Lab Test'),            # Theoretical + sessional type
    (3, 'CT 1'),                # Sessional + CT
    (1, 'Mid'),                 # legacy type not allowed for new records
    (1, 'Viva'),
])
def test_invalid_exam_type_combination_rejected(client, course_id, exam_type):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': course_id, 'exam_type': exam_type, 'faculty_ids': []})
    assert r.status_code == 422
    assert r.json()['detail']['field'] == 'exam_type'
    assert client.writes == []


@pytest.mark.parametrize('exam_type', ['Project Update', 'Evaluation', 'Online Exam', 'Project Presentation', 'Lab Test'])
def test_sessional_types_accepted(client, exam_type):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': 3, 'exam_type': exam_type, 'faculty_ids': [4]})
    assert r.status_code == 201, r.text


def test_faculty_must_belong_to_course(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'faculty_ids': [4]})  # Nafisa not on CSE-415
    assert r.status_code == 422 and r.json()['detail']['field'] == 'faculty_ids'


@pytest.mark.parametrize('field,value', [
    ('notes_link', 'javascript:alert(1)'), ('notes_link', 'drive.google.com/x'),
    ('section', 'A B'), ('exam_date', '2026-02-30'), ('exam_date', '1999-01-01'), ('syllabus', 'x' * 10001),
])
def test_field_validation(client, field, value):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, field: value})
    assert r.status_code == 422
    assert client.writes == []


def test_failed_save_reports_failure(client, monkeypatch):
    def down(**kw):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'save_exam', down)
    r = client.post('/api/exams', headers=h(CR_TOKEN), json=VALID_EXAM)
    assert r.status_code == 503


def test_preview_uses_bot_formatter(client):
    r = client.post('/api/exams/preview', headers=h(CR_TOKEN), json={**VALID_EXAM, 'section': 'a'})
    assert r.status_code == 200
    text = r.json()['text']
    assert 'CSE-415 · Human Computer Interface' in text and 'Section A' in text and 'Ch 1\nCh 2' in text
    assert 'Nazmul Hasan' in text and 'Fairooz' not in text


# --- Webhook -------------------------------------------------------------------
def _messenger_event(mid, text='next exam?'):
    return {'entry': [{'messaging': [{'sender': {'id': 'S1'}, 'message': {'mid': mid, 'text': text}}]}]}


def test_webhook_verification(client):
    # Facebook's real request uses dotted names.
    ok = client.get('/webhook', params={'hub.mode': 'subscribe', 'hub.verify_token': main.VERIFY_TOKEN, 'hub.challenge': '42'})
    assert ok.status_code == 200 and ok.text == '42'
    ok_underscore = client.get('/webhook', params={'hub_mode': 'subscribe', 'hub_verify_token': main.VERIFY_TOKEN, 'hub_challenge': '42'})
    assert ok_underscore.text == '42'
    bad = client.get('/webhook', params={'hub.mode': 'subscribe', 'hub.verify_token': 'nope', 'hub.challenge': '42'})
    assert bad.status_code == 403
    assert client.get('/webhook').status_code == 403


def test_webhook_replies_once_and_splits_long_answers(client, monkeypatch):
    sent = []
    monkeypatch.setattr(main, '_send_page_message', lambda rid, text: sent.append((rid, text)))
    monkeypatch.setattr(main, 'answer', lambda message: type('R', (), {'messages': ['part 1', 'part 2']})())
    event = _messenger_event('m-1')
    assert client.post('/webhook', json=event).status_code == 200
    assert client.post('/webhook', json=event).status_code == 200   # Messenger retry
    assert sent == [('S1', 'part 1'), ('S1', 'part 2')]


def test_webhook_ignores_echoes_and_non_text(client, monkeypatch):
    sent = []
    monkeypatch.setattr(main, '_send_page_message', lambda rid, text: sent.append(text))
    body = {'entry': [{'messaging': [
        {'sender': {'id': 'S1'}, 'message': {'mid': 'e1', 'text': 'x', 'is_echo': True}},
        {'sender': {'id': 'S1'}, 'message': {'mid': 'e2', 'attachments': []}},
    ]}]}
    assert client.post('/webhook', json=body).status_code == 200
    assert sent == []


def test_webhook_signature_enforced_when_secret_set(client, monkeypatch):
    sent = []
    monkeypatch.setattr(main, 'APP_SECRET', 'shh')
    monkeypatch.setattr(main, '_send_page_message', lambda rid, text: sent.append(text))
    monkeypatch.setattr(main, 'answer', lambda message: type('R', (), {'messages': ['ok']})())
    body = json.dumps(_messenger_event('sig-1')).encode()
    assert client.post('/webhook', content=body, headers={'Content-Type': 'application/json'}).status_code == 403
    good = 'sha256=' + hmac.new(b'shh', body, hashlib.sha256).hexdigest()
    r = client.post('/webhook', content=body, headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': good})
    assert r.status_code == 200 and sent == ['ok']


def test_health(client):
    assert client.get('/').json() == {'status': 'ok'}
