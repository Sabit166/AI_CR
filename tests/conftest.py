from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

# Never let tests reach production. db_fetch falls back to the repo's .env and
# main.py calls load_dotenv() (which doesn't override variables that already
# exist), so pin harmless values before anything is imported. Integration
# tests point these at the local Docker PostgREST explicitly.
os.environ['SUPABASE_URL'] = 'http://127.0.0.1:9/rest/v1'
os.environ['SUPABASE_API_KEY'] = 'test-key-not-real'
os.environ['DISCORD_BOT_TOKEN'] = ''
os.environ['SCHEDULER_ENABLED'] = '0'
os.environ['EDITOR_LINK_SECRET'] = 'test-editor-link-secret-0123456789abcdef'
os.environ['SITE_URL'] = 'https://board.example'

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import date_ranges as dr  # noqa: E402
from Chatbot.catalog import Catalog, CatalogCache, build_catalog  # noqa: E402
from db_fetch import ExamQuery  # noqa: E402

CLASS_ID = 1

EXAM_TYPES = [
    {'name': 'CT 1', 'course_type': 'Theoretical', 'sort_order': 10, 'is_legacy': False},
    {'name': 'CT 2', 'course_type': 'Theoretical', 'sort_order': 20, 'is_legacy': False},
    {'name': 'CT 3', 'course_type': 'Theoretical', 'sort_order': 30, 'is_legacy': False},
    {'name': 'Project Update', 'course_type': 'Sessional', 'sort_order': 110, 'is_legacy': False},
    {'name': 'Evaluation', 'course_type': 'Sessional', 'sort_order': 120, 'is_legacy': False},
    {'name': 'Online Exam', 'course_type': 'Sessional', 'sort_order': 130, 'is_legacy': False},
    {'name': 'Project Presentation', 'course_type': 'Sessional', 'sort_order': 140, 'is_legacy': False},
    {'name': 'Lab Test', 'course_type': 'Sessional', 'sort_order': 150, 'is_legacy': False},
    {'name': 'Mid', 'course_type': 'Theoretical', 'sort_order': 25, 'is_legacy': False},
]

F_NAZMUL = {'id': 1, 'name': 'Nazmul Hasan'}
F_FAIROOZ = {'id': 2, 'name': 'Fairooz Tasnia'}
F_SHAHRIAR = {'id': 3, 'name': 'Shahriar Sazzad'}
F_NAFISA = {'id': 4, 'name': 'Nafisa Nawal'}
F_ARIF = {'id': 5, 'name': 'Arif Bhuiyan'}
F_SHAHRIAR_K = {'id': 6, 'name': 'Shahriar Kabir'}

COURSES = [
    {'id': 1, 'code': 'CSE-415', 'title': 'Human Computer Interface', 'course_type': 'Theoretical',
     'aliases': [], 'faculty': [F_FAIROOZ, F_NAZMUL], 'section_faculty': {'A': F_NAZMUL, 'B': F_FAIROOZ}},
    {'id': 2, 'code': 'CSE-427', 'title': 'Digital Image Processing', 'course_type': 'Theoretical',
     'aliases': ['DIP'], 'faculty': [F_FAIROOZ, F_SHAHRIAR], 'section_faculty': {'A': F_FAIROOZ, 'B': F_SHAHRIAR}},
    {'id': 3, 'code': 'CSE-464', 'title': 'Software Development Project II', 'course_type': 'Sessional',
     'aliases': ['Software Development Project-2'], 'faculty': [F_ARIF, F_NAFISA, F_SHAHRIAR], 'section_faculty': {}},
    {'id': 4, 'code': 'CSE-305', 'title': 'Database Management Systems', 'course_type': 'Theoretical',
     'aliases': ['DBMS'], 'faculty': [F_NAZMUL, F_SHAHRIAR_K], 'section_faculty': {'A': F_NAZMUL, 'B': F_SHAHRIAR_K}},
    {'id': 5, 'code': 'CSE-306', 'title': 'Database Management Systems Lab', 'course_type': 'Sessional',
     'aliases': [], 'faculty': [F_NAZMUL, F_SHAHRIAR_K, F_ARIF], 'section_faculty': {}},
    {'id': 6, 'code': 'GEEM-433', 'title': 'Ethics and Morality', 'course_type': 'Theoretical',
     'aliases': [], 'faculty': [F_ARIF, F_FAIROOZ], 'section_faculty': {'A': F_ARIF, 'B': F_FAIROOZ}},
]


def make_catalog(courses=None) -> Catalog:
    return build_catalog(courses if courses is not None else COURSES, EXAM_TYPES)


@pytest.fixture
def catalog() -> Catalog:
    return make_catalog()


@pytest.fixture
def cache(catalog) -> CatalogCache:
    return CatalogCache(loader=lambda class_id: catalog, ttl=3600)


def clock_at(iso: str) -> dr.Clock:
    """clock_at('2026-10-13T10:00') -> a clock fixed at that Asia/Dhaka wall time."""
    moment = datetime.fromisoformat(iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dr.TIMEZONE)
    return lambda: moment


def exam_row(id, course_id, exam_type, exam_date, exam_time='09:00:00', section=None, syllabus=None,
             faculty_ids=None, venue=None, notes_link=None, remarks=None, course_section=None):
    """Mirrors public.exam_details: a Theoretical exam's faculty are its course section(s)' teachers."""
    course = next(c for c in COURSES if c['id'] == course_id)
    by_section = [{'section': s, 'name': f['name'], 'id': f['id']} for s, f in sorted(course['section_faculty'].items())
                  if course_section in (None, s)]
    if by_section:
        faculty = sorted({i['id']: {'id': i['id'], 'name': i['name']} for i in by_section}.values(), key=lambda f: f['name'])
    elif faculty_ids is None:
        faculty = course['faculty']
    else:
        faculty = [f for f in course['faculty'] if f['id'] in faculty_ids]
    return {
        'id': id, 'course_id': course_id, 'course_code': course['code'], 'course_title': course['title'],
        'course_type': course['course_type'], 'course_archived': False, 'exam_type': exam_type,
        'exam_date': exam_date, 'exam_time': exam_time, 'section': section, 'course_section': course_section,
        'section_faculty': [{'section': i['section'], 'name': i['name']} for i in by_section], 'syllabus': syllabus,
        'venue': venue, 'remarks': remarks, 'notes_link': notes_link,
        'faculty_ids': [f['id'] for f in faculty], 'faculty_names': [f['name'] for f in faculty],
        'faculty_source': 'exam' if faculty_ids is not None and not by_section else 'course',
        'exam_faculty_ids': faculty_ids or [], 'legacy_exam_id': None,
        'created_at': '2026-10-01T00:00:00Z', 'updated_at': '2026-10-01T00:00:00Z', 'class_id': CLASS_ID,
    }


class FakeRepo:
    """In-memory stand-in for db_fetch.query_exams with PostgREST filter semantics.
    tests/integration checks the same scenarios against real PostgREST."""

    def __init__(self, rows):
        self.rows = rows
        self.queries: list[ExamQuery] = []

    def query_exams(self, q: ExamQuery) -> list[dict]:
        self.queries.append(q)
        out = []
        for row in self.rows:
            if q.class_id is not None and row.get('class_id', CLASS_ID) != q.class_id:
                continue
            if q.course_ids is not None and row['course_id'] not in q.course_ids:
                continue
            if q.exam_types is not None and row['exam_type'] not in q.exam_types:
                continue
            if q.faculty_ids is not None and not set(row['faculty_ids']) & set(q.faculty_ids):
                continue
            if q.section is not None and (row['section'] not in (None, q.section)
                                          or row.get('course_section') not in (None, q.section)):
                continue
            d = date.fromisoformat(row['exam_date'])
            if q.date_from is not None and d < q.date_from:
                continue
            if q.date_to is not None and d > q.date_to:
                continue
            out.append(row)
        out.sort(key=lambda r: (r['exam_date'], r['exam_time'] or '', r['course_code'], r['id']), reverse=q.descending)
        out = out[q.offset:q.offset + q.limit]
        return [{k: v for k, v in r.items() if k in q.select} for r in out]
