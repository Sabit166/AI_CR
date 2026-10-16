"""Class exam board: read-only, no sign-in, one class per link, no internal fields, cached."""
import pytest
from fastapi.testclient import TestClient

import auth
import db_fetch
import links
import main
import public_api
from Chatbot import catalog as catalog_mod
from conftest import CLASS_ID, COURSES, EXAM_TYPES, exam_row

KEY = '6f1d1d4e-1111-4111-8111-111111111111'
CLASS = {'id': CLASS_ID, 'name': 'CSE 22', 'discord_channel_id': '900000000000000002', 'cr_role_id': None,
         'view_key': KEY, 'auto_updates': True, 'archived_at': None}
BASE = f'/api/public/classes/{KEY}'


@pytest.fixture
def client(monkeypatch):
    auth.clear_auth_cache()
    public_api.invalidate()
    calls = []

    def fake_query(query):
        calls.append(query)
        rows = [exam_row(1, 1, 'CT 1', '2026-10-20', syllabus='Ch 1'), exam_row(2, 2, 'Lab Test', '2026-10-21')]
        return [{k: r[k] for k in query.select} for r in rows][: query.limit]

    monkeypatch.setattr(db_fetch, 'query_exams', fake_query)
    monkeypatch.setattr(db_fetch, 'fetch_class_by_view_key', lambda key: CLASS if key == KEY else None)
    monkeypatch.setattr(db_fetch, 'fetch_class', lambda cid: CLASS if cid == CLASS_ID else None)
    monkeypatch.setattr(db_fetch, 'get_exam', lambda eid: exam_row(eid, 1, 'CT 1', '2026-10-20'))
    monkeypatch.setattr(db_fetch, 'delete_exam', lambda exam_id: True)
    monkeypatch.setattr(catalog_mod.catalog_cache, 'get', lambda class_id: catalog_mod.build_catalog(COURSES, EXAM_TYPES))
    test_client = TestClient(main.app)
    test_client.calls = calls
    return test_client


def test_class_name_without_sign_in(client):
    body = client.get(BASE).json()
    assert body['name'] == 'CSE 22' and body['today']


def test_upcoming_exams_without_sign_in(client):
    response = client.get(f'{BASE}/exams')
    assert response.status_code == 200
    body = response.json()
    assert [e['exam_type'] for e in body['exams']] == ['CT 1', 'Lab Test']
    assert body['has_more'] is False and body['today']
    assert 'public' in response.headers['cache-control']
    query = client.calls[0]
    assert query.class_id == CLASS_ID
    assert query.date_from is not None and query.date_to is None and not query.descending


@pytest.mark.parametrize('key', ['6f1d1d4e-9999-4999-8999-999999999999', 'not-a-uuid', '1'])
def test_unknown_class_link_is_404(client, key):
    for path in ('', '/exams', '/courses'):
        response = client.get(f'/api/public/classes/{key}{path}')
        assert response.status_code == 404 and '/exams' in response.json()['detail']['message']
    assert client.calls == []


def test_old_single_class_routes_are_gone(client):
    assert client.get('/api/public/exams').status_code == 404


def test_only_student_facing_fields_are_exposed(client):
    exam = client.get(f'{BASE}/exams').json()['exams'][0]
    assert set(exam) == set(public_api.PUBLIC_EXAM_FIELDS)
    for internal in ('created_at', 'updated_at', 'legacy_exam_id', 'faculty_ids', 'exam_faculty_ids', 'class_id'):
        assert internal not in exam


def test_past_scope_and_course_filter(client):
    client.get(f'{BASE}/exams?scope=past&course_id=2&limit=5')
    query = client.calls[0]
    assert query.descending and query.date_to is not None and query.course_ids == (2,)
    assert query.limit == 6


@pytest.mark.parametrize('params', ['scope=all', 'limit=0', 'limit=500', 'offset=-1', 'course_id=abc', 'course_id=0'])
def test_rejects_bad_parameters(client, params):
    assert client.get(f'{BASE}/exams?{params}').status_code == 422


@pytest.mark.parametrize('method,path', [
    ('post', f'{BASE}/exams'), ('patch', f'{BASE}/exams'), ('delete', f'{BASE}/exams'), ('post', f'{BASE}/courses'),
])
def test_public_board_is_read_only(client, method, path):
    assert getattr(client, method)(path).status_code == 405


def test_board_link_is_not_an_editor_link(client):
    assert client.get('/api/courses', headers={'Authorization': f'Bearer {KEY}'}).status_code == 401


def test_responses_are_cached_and_cleared_by_cr_writes(client):
    client.get(f'{BASE}/exams')
    client.get(f'{BASE}/exams')
    assert len(client.calls) == 1
    token = links.make_editor_token(CLASS_ID, '123456789012345678')
    assert client.delete('/api/exams/7', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    client.get(f'{BASE}/exams')
    assert len(client.calls) == 2


def test_database_outage_is_a_friendly_503(client, monkeypatch):
    def boom(query):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'query_exams', boom)
    response = client.get(f'{BASE}/exams?scope=past')
    assert response.status_code == 503
    assert 'temporarily unavailable' in response.json()['detail']['message']


def test_courses_list(client):
    courses = client.get(f'{BASE}/courses').json()['courses']
    assert [c['code'] for c in courses] == sorted(c['code'] for c in COURSES)
    assert set(courses[0]) == {'id', 'code', 'title', 'course_type'}
