"""Runtime course configuration for the student agent.

The catalog (active courses, their faculty, exam types) is loaded from Supabase
and cached briefly. Freshness rules:
  * CR writes in this process call `invalidate()`, so the next student question
    reloads immediately.
  * Otherwise entries expire after CATALOG_TTL_SECONDS (default 60s), which
    bounds staleness for edits made outside this process (e.g. dashboard SQL).
  * If a reload fails we raise instead of silently serving the stale copy.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import db_fetch

CATALOG_TTL_SECONDS = float(os.getenv('CATALOG_TTL_SECONDS', '60'))

_STOPWORDS = {'and', 'of', 'the', 'to', 'in', 'for', '&', 'a', 'an', 'on', 'with'}
_ROMAN = {'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'v': '5'}


def normalize_text(text: str) -> str:
    """Lowercase, alphanumerics only, single spaces."""
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).split())


@dataclass(frozen=True)
class Faculty:
    id: int
    name: str


@dataclass(frozen=True)
class Course:
    id: int
    code: str
    title: str
    course_type: str
    aliases: tuple[str, ...] = ()
    faculty: tuple[Faculty, ...] = ()

    @property
    def prefix(self) -> str:
        return self.code.split('-')[0]

    @property
    def number(self) -> str:
        return self.code.split('-')[1]

    def acronyms(self) -> set[str]:
        """'Software Development Project II' -> {'sdp', 'sdp2', 'sdpii'}; also for aliases."""
        result: set[str] = set()
        for name in (self.title, *self.aliases):
            words = [w for w in normalize_text(name).split() if w not in _STOPWORDS]
            letters = [w for w in words if w not in _ROMAN and not w.isdigit()]
            numerals = [_ROMAN.get(w, w) for w in words if w in _ROMAN or w.isdigit()]
            if len(letters) >= 2:
                base = ''.join(w[0] for w in letters)
                result.add(base)
                for numeral in numerals:
                    result.add(base + numeral)
                    roman = {v: k for k, v in _ROMAN.items()}.get(numeral)
                    if roman:
                        result.add(base + roman)
        return result


@dataclass(frozen=True)
class ExamType:
    name: str
    course_type: str
    is_legacy: bool


@dataclass(frozen=True)
class Catalog:
    courses: tuple[Course, ...]
    exam_types: tuple[ExamType, ...]
    loaded_at: float = field(default_factory=time.monotonic)

    def course_by_id(self, course_id: int) -> Course | None:
        return next((c for c in self.courses if c.id == course_id), None)

    def exam_type_names(self, include_legacy: bool = True) -> list[str]:
        return [t.name for t in self.exam_types if include_legacy or not t.is_legacy]

    def exam_types_for(self, course_type: str, include_legacy: bool = False) -> list[str]:
        return [t.name for t in self.exam_types if t.course_type == course_type and (include_legacy or not t.is_legacy)]

    def all_faculty(self) -> list[Faculty]:
        seen: dict[int, Faculty] = {}
        for course in self.courses:
            for member in course.faculty:
                seen[member.id] = member
        return sorted(seen.values(), key=lambda f: f.name.lower())


def build_catalog(course_rows: list[dict], exam_type_rows: list[dict]) -> Catalog:
    courses = tuple(
        Course(
            id=row['id'],
            code=row['code'],
            title=row['title'],
            course_type=row['course_type'],
            aliases=tuple(row.get('aliases') or ()),
            faculty=tuple(Faculty(f['id'], f['name']) for f in row.get('faculty') or ()),
        )
        for row in course_rows
    )
    exam_types = tuple(
        ExamType(row['name'], row['course_type'], bool(row.get('is_legacy')))
        for row in exam_type_rows
    )
    return Catalog(courses, exam_types)


def load_catalog_from_db() -> Catalog:
    return build_catalog(db_fetch.fetch_active_courses(), db_fetch.fetch_exam_types())


class CatalogCache:
    def __init__(self, loader: Callable[[], Catalog] = load_catalog_from_db, ttl: float = CATALOG_TTL_SECONDS):
        self._loader = loader
        self._ttl = ttl
        self._lock = threading.Lock()
        self._catalog: Catalog | None = None
        self._generation = 0

    def get(self) -> Catalog:
        with self._lock:
            catalog = self._catalog
            if catalog is not None and time.monotonic() - catalog.loaded_at < self._ttl:
                return catalog
            generation = self._generation

        fresh = self._loader()  # raises on failure: never fall back to a stale copy

        with self._lock:
            # Don't overwrite if invalidate() ran while we were loading.
            if generation == self._generation:
                self._catalog = fresh
        return fresh

    def invalidate(self) -> None:
        with self._lock:
            self._catalog = None
            self._generation += 1


catalog_cache = CatalogCache()
