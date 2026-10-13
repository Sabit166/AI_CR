"""Public student board: read-only, no sign-in, no internal fields, cached."""
import pytest
from fastapi.testclient import TestClient

import auth
import db_fetch
import main
import public_api
from Chatbot import catalog as catalog_mod
from conftest import COURSES, EXAM_TYPES, exam_row

CR_TOKEN = 'cr-token'


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
    monkeypatch.setattr(db_fetch, 'fetch_auth_user', lambda token: {'id': '11111111-1111-1111-1111-111111111111', 'email': 'cr@example.com'} if token == CR_TOKEN else None)
    monkeypatch.setattr(db_fetch, 'is_cr_member', lambda user_id: True)
    monkeypatch.setattr(db_fetch, 'delete_exam', lambda exam_id: True)
    monkeypatch.setattr(catalog_mod.catalog_cache, 'get', lambda: catalog_mod.build_catalog(COURSES, EXAM_TYPES))
    test_client = TestClient(main.app)
    test_client.calls = calls
    return test_client


def test_upcoming_exams_without_sign_in(client):
    response = client.get('/api/public/exams')
    assert response.status_code == 200
    body = response.json()
    assert [e['exam_type'] for e in body['exams']] == ['CT 1', 'Lab Test']
    assert body['has_more'] is False and body['today']
    assert 'public' in response.headers['cache-control']
    query = client.calls[0]
    assert query.date_from is not None and query.date_to is None and not query.descending


def test_only_student_facing_fields_are_exposed(client):
    exam = client.get('/api/public/exams').json()['exams'][0]
    assert set(exam) == set(public_api.PUBLIC_EXAM_FIELDS)
    for internal in ('created_at', 'updated_at', 'legacy_exam_id', 'faculty_ids', 'exam_faculty_ids'):
        assert internal not in exam


def test_past_scope_and_course_filter(client):
    client.get('/api/public/exams?scope=past&course_id=2&limit=5')
    query = client.calls[0]
    assert query.descending and query.date_to is not None and query.course_ids == (2,)
    assert query.limit == 6


@pytest.mark.parametrize('params', ['scope=all', 'limit=0', 'limit=500', 'offset=-1', 'course_id=abc', 'course_id=0'])
def test_rejects_bad_parameters(client, params):
    assert client.get(f'/api/public/exams?{params}').status_code == 422


@pytest.mark.parametrize('method,path', [
    ('post', '/api/public/exams'), ('patch', '/api/public/exams'), ('delete', '/api/public/exams'),
    ('post', '/api/public/courses'),
])
def test_public_board_is_read_only(client, method, path):
    assert getattr(client, method)(path).status_code == 405


def test_responses_are_cached_and_cleared_by_cr_writes(client):
    client.get('/api/public/exams')
    client.get('/api/public/exams')
    assert len(client.calls) == 1
    assert client.delete('/api/exams/7', headers={'Authorization': f'Bearer {CR_TOKEN}'}).status_code == 200
    client.get('/api/public/exams')
    assert len(client.calls) == 2


def test_database_outage_is_a_friendly_503(client, monkeypatch):
    def boom(query):
        raise db_fetch.DatabaseError('down', code='unavailable')
    monkeypatch.setattr(db_fetch, 'query_exams', boom)
    response = client.get('/api/public/exams?scope=past')
    assert response.status_code == 503
    assert 'temporarily unavailable' in response.json()['detail']['message']


def test_courses_list(client):
    courses = client.get('/api/public/courses').json()['courses']
    assert [c['code'] for c in courses] == sorted(c['code'] for c in COURSES)
    assert set(courses[0]) == {'id', 'code', 'title', 'course_type'}
