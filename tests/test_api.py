"""CR editor API: editor-link authorization, class scoping, server-side validation and
posting to Discord (database layer and Discord stubbed).
tests/integration/test_db.py runs the same writes against real Postgres."""
import time

import pytest
from fastapi.testclient import TestClient

import auth
import cr_api
import db_fetch
import links
import main
from conftest import CLASS_ID, COURSES, EXAM_TYPES, exam_row
from discord_bot import client as discord

CR_USER = '123456789012345678'
OTHER_CLASS = 2
CLASSES = {
    CLASS_ID: {'id': CLASS_ID, 'name': 'CSE 22', 'discord_guild_id': '900000000000000001',
               'discord_channel_id': '900000000000000002', 'cr_role_id': None,
               'view_key': '6f1d1d4e-1111-4111-8111-111111111111', 'auto_updates': True, 'archived_at': None},
    OTHER_CLASS: {'id': OTHER_CLASS, 'name': 'EEE 22', 'discord_guild_id': '900000000000000001',
                  'discord_channel_id': '900000000000000003', 'cr_role_id': None,
                  'view_key': '6f1d1d4e-2222-4222-8222-222222222222', 'auto_updates': True, 'archived_at': None},
}
CR_TOKEN = links.make_editor_token(CLASS_ID, CR_USER)
OTHER_CLASS_TOKEN = links.make_editor_token(OTHER_CLASS, CR_USER)


@pytest.fixture
def client(monkeypatch):
    auth.clear_auth_cache()
    cr_api._recent_posts.clear()
    monkeypatch.setattr(db_fetch, 'fetch_class', lambda cid: CLASSES.get(cid))
    monkeypatch.setattr(db_fetch, 'fetch_exam_types', lambda: EXAM_TYPES)
    courses = {c['id']: {**c, 'class_id': CLASS_ID, 'archived_at': None, 'faculty_exception_note': None} for c in COURSES}
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: courses.get(cid))
    writes = []
    monkeypatch.setattr(db_fetch, 'save_course', lambda **kw: writes.append(('course', kw)) or 99)
    monkeypatch.setattr(db_fetch, 'save_exam', lambda **kw: writes.append(('exam', kw)) or 500)
    monkeypatch.setattr(db_fetch, 'delete_exam', lambda exam_id: writes.append(('delete', exam_id)) or True)
    monkeypatch.setattr(db_fetch, 'remove_course', lambda class_id, cid: writes.append(('remove_course', class_id, cid)) or 'archived')
    monkeypatch.setattr(db_fetch, 'get_exam', lambda eid: exam_row(eid, 1, 'CT 1', '2026-10-20') if eid in (500, 7) else None)
    posted = []
    monkeypatch.setattr(discord, 'post_messages', lambda channel, messages: posted.append((channel, messages)))
    test_client = TestClient(main.app)
    test_client.writes = writes
    test_client.posted = posted
    return test_client


def h(token):
    return {'Authorization': f'Bearer {token}'}


VALID_EXAM = {'course_id': 1, 'exam_type': 'CT 1', 'exam_date': '2026-10-20', 'exam_time': '09:00',
              'syllabus': 'Ch 1\nCh 2', 'faculty_ids': [1]}


# --- Editor links ---------------------------------------------------------------
@pytest.mark.parametrize('method,path', [
    ('get', '/api/courses'), ('post', '/api/courses'), ('patch', '/api/courses/1'), ('delete', '/api/courses/1'),
    ('get', '/api/faculty'), ('post', '/api/faculty'), ('delete', '/api/faculty/1'),
    ('get', '/api/exams'), ('post', '/api/exams'), ('patch', '/api/exams/7'), ('delete', '/api/exams/7'),
    ('get', '/api/config'), ('get', '/api/me'), ('patch', '/api/class'),
    ('post', '/api/discord/post'), ('post', '/api/discord/post/exams/7'),
])
def test_requires_editor_link(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers=h('forged')).status_code == 401
    assert client.writes == [] and client.posted == []


def test_tampered_link_is_rejected(client):
    *payload, signature = CR_TOKEN.split('.')
    forged_class = '.'.join([payload[0], str(OTHER_CLASS), *payload[2:], signature])
    assert client.get('/api/me', headers=h(forged_class)).status_code == 401
    other_secret = CR_TOKEN[:-4] + ('AAAA' if not CR_TOKEN.endswith('AAAA') else 'BBBB')
    assert client.get('/api/me', headers=h(other_secret)).status_code == 401


def test_expired_link_is_rejected(client):
    old = links.make_editor_token(CLASS_ID, CR_USER, now=time.time() - 30 * 3600)
    r = client.get('/api/me', headers=h(old))
    assert r.status_code == 401 and '/manage' in r.json()['detail']['message']


def test_me_names_the_class(client):
    body = client.get('/api/me', headers=h(CR_TOKEN)).json()
    assert body['class']['name'] == 'CSE 22' and body['class']['linked'] is True
    assert body['class']['board_url'] == 'https://board.example/c/6f1d1d4e-1111-4111-8111-111111111111'
    assert body['user_id'] == CR_USER


def test_removed_class_link_is_forbidden(client, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_class', lambda cid: None)
    assert client.get('/api/courses', headers=h(CR_TOKEN)).status_code == 403


def test_link_check_outage_is_503_not_access(client, monkeypatch):
    auth.clear_auth_cache()

    def down(cid):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'fetch_class', down)
    assert client.get('/api/courses', headers=h(CR_TOKEN)).status_code == 503


# --- A link only reaches its own class ------------------------------------------
def test_lists_are_scoped_to_the_link_class(client, monkeypatch):
    seen = []
    monkeypatch.setattr(db_fetch, 'fetch_active_courses', lambda class_id, with_exam_counts=False: seen.append(class_id) or [])
    monkeypatch.setattr(db_fetch, 'fetch_faculty', lambda class_id: seen.append(class_id) or [])
    monkeypatch.setattr(db_fetch, 'query_exams', lambda q: seen.append(q.class_id) or [])
    for path in ('/api/courses', '/api/faculty', '/api/exams'):
        assert client.get(path, headers=h(OTHER_CLASS_TOKEN)).status_code == 200
    assert seen == [OTHER_CLASS] * 3


@pytest.mark.parametrize('method,path,body', [
    ('patch', '/api/exams/7', VALID_EXAM),
    ('delete', '/api/exams/7', None),
    ('get', '/api/exams/7', None),
    ('post', '/api/discord/post/exams/7', None),
])
def test_other_class_exam_is_not_found(client, method, path, body):
    kwargs = {'headers': h(OTHER_CLASS_TOKEN)}
    if body is not None:
        kwargs['json'] = body
    assert getattr(client, method)(path, **kwargs).status_code == 404
    assert client.writes == [] and client.posted == []


def test_other_class_course_cannot_get_exams(client):
    r = client.post('/api/exams', headers=h(OTHER_CLASS_TOKEN), json=VALID_EXAM)
    assert r.status_code == 422 and r.json()['detail']['field'] == 'course_id'
    assert client.writes == []


def test_writes_name_the_class(client):
    client.post('/api/exams', headers=h(CR_TOKEN), json=VALID_EXAM)
    client.delete('/api/courses/1', headers=h(OTHER_CLASS_TOKEN))
    assert client.writes[0][1]['class_id'] == CLASS_ID
    assert client.writes[1] == ('remove_course', OTHER_CLASS, 1)


def test_legacy_unauthenticated_exam_endpoints_are_gone(client):
    assert client.post('/exams', json={'Course Code': 'X'}).status_code in (404, 405)
    assert client.delete('/exams/1').status_code in (404, 405)
    assert client.post('/webhook', json={}).status_code == 404  # Messenger is gone


# --- Course validation ---------------------------------------------------------
def test_create_theoretical_course(client, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: {'id': cid, 'code': 'CSE-433'})
    r = client.post('/api/courses', headers=h(CR_TOKEN),
                    json={'code': 'cse 433', 'title': '  Compiler   Design ', 'aliases': ['CD', 'CD', ' '],
                          'section_faculty': {'a': 2, 'B': 1}, 'faculty_ids': [5]})
    assert r.status_code == 201, r.text
    kind, kw = client.writes[0]
    assert kw['code'] == 'CSE-433' and kw['title'] == 'Compiler Design' and kw['aliases'] == ['CD']
    # Theoretical teachers are exactly the section teachers; stray faculty_ids are ignored.
    assert kw['section_faculty'] == {'A': 2, 'B': 1} and kw['faculty_ids'] == [1, 2]


@pytest.mark.parametrize('code', ['CSE-433A', '433', 'C-433', ''])
def test_invalid_course_code_rejected(client, code):
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={'code': code, 'title': 'X Y', 'section_faculty': {'A': 1, 'B': 2}})
    assert r.status_code == 422
    assert r.json()['detail']['field'] == 'code'
    assert client.writes == []


@pytest.mark.parametrize('code,body,ok', [
    ('CSE-433', {'section_faculty': {'A': 1, 'B': 2}}, True),
    ('CSE-433', {'section_faculty': {'A': 1, 'B': 1}}, True),    # one teacher takes both sections
    ('CSE-433', {'section_faculty': {'A': 1}}, False),
    ('CSE-433', {'faculty_ids': [1, 2]}, False),                # no section assignment
    ('CSE-434', {}, True), ('CSE-434', {'faculty_ids': [1]}, True), ('CSE-434', {'faculty_ids': [1, 2, 3, 4, 5]}, True),
    ('CSE-434', {'faculty_ids': [1], 'section_faculty': {'A': 1}}, True),  # Sessional: sections dropped
])
def test_course_faculty_rules(client, monkeypatch, code, body, ok):
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: {'id': cid})
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={'code': code, 'title': 'Course', **body})
    assert (r.status_code == 201) == ok, r.text
    if ok:
        kw = client.writes[0][1]
        if code == 'CSE-434':
            assert kw['section_faculty'] == {} and kw['faculty_ids'] == sorted(set(body.get('faculty_ids', [])))
    else:
        assert r.json()['detail']['field'] == 'section_faculty'
        assert 'Section' in r.json()['detail']['message']


def test_unknown_course_section_rejected(client):
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={
        'code': 'CSE-433', 'title': 'Course', 'section_faculty': {'A': 1, 'C': 2}})
    assert r.status_code == 422 and client.writes == []


def test_exception_note_is_ignored(client, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: {'id': cid})
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={
        'code': 'CSE-434', 'title': 'Course', 'faculty_ids': [1], 'faculty_exception_note': 'old client'})
    assert r.status_code == 201
    assert 'faculty_exception_note' not in client.writes[0][1]


def test_duplicate_course_conflict(client, monkeypatch):
    def dup(**kw):
        raise db_fetch.DatabaseError('dup', code='duplicate', status=409)
    monkeypatch.setattr(db_fetch, 'save_course', dup)
    r = client.post('/api/courses', headers=h(CR_TOKEN), json={'code': 'CSE-415', 'title': 'HCI', 'section_faculty': {'A': 1, 'B': 2}})
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
    assert kw['actor'] == CR_USER and kw['client_request_id'] == '3f1e4c1a-0000-4000-8000-000000000001'
    assert kw['syllabus'] == 'Ch 1\nCh 2'


@pytest.mark.parametrize('course_id,exam_type', [
    (1, 'Lab Test'),            # Theoretical + sessional type
    (3, 'CT 1'),                # Sessional + CT
    (3, 'Mid'),                 # Mid is Theoretical only
    (1, 'Viva'),
])
def test_invalid_exam_type_combination_rejected(client, course_id, exam_type):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': course_id, 'exam_type': exam_type, 'faculty_ids': []})
    assert r.status_code == 422
    assert r.json()['detail']['field'] == 'exam_type'
    assert client.writes == []


@pytest.mark.parametrize('exam_type', ['CT 1', 'CT 2', 'Mid', 'CT 3'])
def test_theoretical_types_accepted(client, exam_type):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'exam_type': exam_type})
    assert r.status_code == 201, r.text


def test_theoretical_exam_has_no_class_section(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'section': 'B'})
    assert r.status_code == 201, r.text
    assert client.writes[0][1]['section'] is None
    # A class section is irrelevant for a Theoretical course, so even an invalid one is not an error.
    assert client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'section': 'A B'}).status_code == 201


@pytest.mark.parametrize('course_section,stored', [(None, None), ('', None), ('a', 'A'), ('B', 'B')])
def test_theoretical_exam_course_section(client, course_section, stored):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_section': course_section})
    assert r.status_code == 201, r.text
    kw = client.writes[0][1]
    assert kw['course_section'] == stored
    assert kw['faculty_ids'] == []  # teachers come from the course section


def test_invalid_course_section_rejected(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_section': 'C'})
    assert r.status_code == 422 and r.json()['detail']['field'] == 'course_section'


def test_theoretical_exam_needs_section_teacher(client, monkeypatch):
    course = {**COURSES[0], 'class_id': CLASS_ID, 'archived_at': None, 'section_faculty': {'A': COURSES[0]['faculty'][0]}}
    monkeypatch.setattr(db_fetch, 'fetch_course', lambda cid: course)
    assert client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_section': 'A'}).status_code == 201
    for course_section in ('B', None):
        r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_section': course_section})
        assert r.status_code == 422 and 'Section B' in r.json()['detail']['message']


def test_sessional_exam_ignores_course_section(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': 3, 'exam_type': 'Lab Test',
                                                             'faculty_ids': [4], 'course_section': 'A'})
    assert r.status_code == 201, r.text
    assert client.writes[0][1]['course_section'] is None


def test_sessional_exam_keeps_section(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': 3, 'exam_type': 'Lab Test',
                                                             'faculty_ids': [4], 'section': 'b'})
    assert r.status_code == 201, r.text
    assert client.writes[0][1]['section'] == 'B'


@pytest.mark.parametrize('exam_type', ['Project Update', 'Evaluation', 'Online Exam', 'Project Presentation', 'Lab Test'])
def test_sessional_types_accepted(client, exam_type):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': 3, 'exam_type': exam_type, 'faculty_ids': [4]})
    assert r.status_code == 201, r.text


def test_faculty_must_belong_to_course(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': 3, 'exam_type': 'Lab Test',
                                                             'faculty_ids': [1]})  # Nazmul not on CSE-464
    assert r.status_code == 422 and r.json()['detail']['field'] == 'faculty_ids'


@pytest.mark.parametrize('field,value', [
    ('notes_link', 'javascript:alert(1)'), ('notes_link', 'drive.google.com/x'),
    ('exam_date', '2026-02-30'), ('exam_date', '1999-01-01'), ('syllabus', 'x' * 10001),
])
def test_field_validation(client, field, value):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, field: value})
    assert r.status_code == 422
    assert client.writes == []


def test_invalid_section_rejected_for_sessional(client):
    r = client.post('/api/exams', headers=h(CR_TOKEN), json={**VALID_EXAM, 'course_id': 3, 'exam_type': 'Lab Test',
                                                             'faculty_ids': [4], 'section': 'A B'})
    assert r.status_code == 422 and r.json()['detail']['field'] == 'section'


def test_failed_save_reports_failure(client, monkeypatch):
    def down(**kw):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'save_exam', down)
    r = client.post('/api/exams', headers=h(CR_TOKEN), json=VALID_EXAM)
    assert r.status_code == 503


def test_preview_uses_bot_formatter(client):
    r = client.post('/api/exams/preview', headers=h(CR_TOKEN), json={**VALID_EXAM, 'section': 'x', 'course_section': 'b'})
    assert r.status_code == 200
    text = r.json()['text']
    assert 'CSE-415 · Human Computer Interface' in text and 'Ch 1\nCh 2' in text
    assert '📝 CT 1 · Course Section B' in text and 'Section X' not in text
    assert '👤 Faculty: Fairooz Tasnia' in text and 'Nazmul' not in text  # Section B's teacher only


def test_preview_both_sections_lists_each_teacher(client):
    r = client.post('/api/exams/preview', headers=h(CR_TOKEN), json=VALID_EXAM)
    text = r.json()['text']
    assert '📝 CT 1 · Course Sections A & B' in text
    assert '👤 Faculty: Course Section A: Nazmul Hasan · Course Section B: Fairooz Tasnia' in text



# --- Post to Discord -----------------------------------------------------------
@pytest.fixture
def exams_this_week(monkeypatch):
    rows = [exam_row(1, 1, 'CT 2', '2026-10-20', exam_time='10:00:00', syllabus='Ch 3'),
            exam_row(2, 3, 'Lab Test', '2026-10-21', notes_link='https://drive.example/n')]
    monkeypatch.setattr(cr_api.dr, 'now_local', lambda clock=None: __import__('conftest').clock_at('2026-10-18T09:00')())
    monkeypatch.setattr(db_fetch, 'query_exams', lambda q: [r for r in rows
                                                            if q.date_from.isoformat() <= r['exam_date']
                                                            and (q.date_to is None or r['exam_date'] <= q.date_to.isoformat())])
    return rows


@pytest.mark.parametrize('kind,expect', [
    ('this_week', "This week's exams"), ('next_week', "Next week's exams"),
    ('next_exam_day', 'Next exam day'), ('next_exam_notes', 'Notes for the next exam day'),
])
def test_post_update_to_class_channel(client, exams_this_week, kind, expect):
    r = client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': kind})
    assert r.status_code == 200, r.text
    channel, messages = client.posted[0]
    assert channel == CLASSES[CLASS_ID]['discord_channel_id']
    assert expect in messages[0]


def test_post_single_exam(client, exams_this_week):
    r = client.post('/api/discord/post/exams/7', headers=h(CR_TOKEN))
    assert r.status_code == 200 and r.json()['exam_count'] == 1
    assert 'Exam update' in client.posted[0][1][0] and 'CSE-415' in client.posted[0][1][0]


def test_double_tap_posts_once(client, exams_this_week):
    assert client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': 'next_week'}).status_code == 200
    assert client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': 'next_week'}).status_code == 429
    assert len(client.posted) == 1


def test_bot_without_channel_access_is_explained(client, exams_this_week, monkeypatch):
    def denied(channel, messages):
        raise discord.DiscordError('403', status=403, code=discord.MISSING_ACCESS)
    monkeypatch.setattr(discord, 'post_messages', denied)
    r = client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': 'this_week'})
    assert r.status_code == 502 and 'Send Messages' in r.json()['detail']['message']
    # A failed post doesn't block retrying straight away.
    monkeypatch.setattr(discord, 'post_messages', lambda channel, messages: client.posted.append(channel))
    assert client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': 'this_week'}).status_code == 200


def test_unlinked_class_cannot_post(client, monkeypatch):
    monkeypatch.setattr(db_fetch, 'fetch_class', lambda cid: {**CLASSES[CLASS_ID], 'discord_channel_id': None})
    r = client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': 'this_week'})
    assert r.status_code == 409 and '/setup' in r.json()['detail']['message']


def test_unknown_post_kind_rejected(client):
    assert client.post('/api/discord/post', headers=h(CR_TOKEN), json={'kind': 'everything'}).status_code == 422


def test_toggle_auto_updates(client, monkeypatch):
    changes = []
    monkeypatch.setattr(db_fetch, 'update_class', lambda cid, ch, **kw: changes.append((cid, ch)) or {**CLASSES[cid], **ch})
    r = client.patch('/api/class', headers=h(CR_TOKEN), json={'auto_updates': False})
    assert r.status_code == 200 and r.json()['class']['auto_updates'] is False
    assert changes == [(CLASS_ID, {'auto_updates': False})]


def test_health(client):
    assert client.get('/').json() == {'status': 'ok'}


def test_cron_tick_needs_secret(client, monkeypatch):
    assert client.post('/cron/tick').status_code == 404  # not enabled without CRON_SECRET
    monkeypatch.setenv('CRON_SECRET', 's3cret')
    monkeypatch.setattr(main.scheduler, 'run_tick', lambda: {'sent': 1})
    assert client.post('/cron/tick', headers={'X-Cron-Secret': 'nope'}).status_code == 403
    assert client.post('/cron/tick', headers={'X-Cron-Secret': 's3cret'}).json() == {'result': {'sent': 1}}
