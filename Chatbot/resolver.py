"""Deterministic resolution of course / faculty mentions against the live catalog.

Order of evidence for a course mention (first stage that yields a match wins):
  1. Course code ("CSE-415", "cse 415", "415")
  2. Exact title or configured alias
  3. Acronym of the title/alias ("HCI", "SDP2", "SDP II")
  4. Department prefix ("GEEM", "CSE") -> every active course with that prefix
  5. Word containment ("database", "image processing")
  6. Fuzzy similarity (typos), tightly thresholded

A stage that matches several courses yields an *ambiguous* result; the bot then
asks the student to clarify instead of picking one.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from academic import normalize_course_code

from .catalog import Catalog, Course, Faculty, normalize_text

FUZZY_THRESHOLD = 0.84
_HONORIFIC_WORDS = {'sir', 'madam', 'mam', 'maam', 'miss', 'mr', 'mrs', 'ms', 'dr', 'prof', 'professor',
                    'major', 'maj', 'apu', 'bhai', 'teacher', 'of', 'by', 'the'}
_GENERIC_WORDS = {'exam', 'exams', 'course', 'courses', 'class', 'test', 'tests', 'the', 'of', 'and', 'next',
                  'upcoming', 'my', 'our', 'subject', 'paper', 'lab', 'theory', 'sessional',
                  'ct', 'cts', 'mid', 'midterm', 'quiz', 'final', 'syllabus'}
_CODE_IN_TEXT_RE = re.compile(r'\b([A-Za-z]{2,5})([\s_-]*)([0-9]{3,4})\b')
_NOT_PREFIXES = {'on', 'in', 'at', 'by', 'of', 'to', 'is', 'it', 'the', 'and', 'for', 'from', 'till', 'until',
                 'year', 'room', 'sec', 'after', 'since', 'before', 'about', 'than', 'only', 'page', 'pages', 'ch'}


@dataclass
class MentionResult:
    mention: str
    courses: list[Course] = field(default_factory=list)
    ambiguous: bool = False
    group: bool = False          # matched a department prefix (intentionally several courses)

    @property
    def matched(self) -> bool:
        return bool(self.courses)


@dataclass
class CourseResolution:
    results: list[MentionResult] = field(default_factory=list)

    @property
    def course_ids(self) -> list[int]:
        ids: list[int] = []
        for result in self.results:
            if result.matched and not result.ambiguous:
                ids += [c.id for c in result.courses]
        return list(dict.fromkeys(ids))

    @property
    def ambiguous(self) -> list[MentionResult]:
        return [r for r in self.results if r.ambiguous]

    @property
    def unmatched(self) -> list[MentionResult]:
        return [r for r in self.results if not r.matched]


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith('s') else word


def _words(text: str, drop: set[str] = frozenset()) -> list[str]:
    return [_stem(w) for w in normalize_text(text).split() if w not in drop]


def codes_in_text(text: str, known_prefixes: set[str] | None = None) -> list[str]:
    """Course codes literally written in the text. "on 2026" is not a code: a prefix separated
    by a space only counts when it is a configured department (e.g. "cse 415")."""
    codes = []
    for prefix, separator, number in _CODE_IN_TEXT_RE.findall(text or ''):
        if prefix.lower() in _NOT_PREFIXES:
            continue
        if separator.isspace() and prefix.upper() not in (known_prefixes or set()):
            continue
        code = normalize_course_code(f'{prefix}-{number}')
        if code:
            codes.append(code)
    return list(dict.fromkeys(codes))


def resolve_course_mention(mention: str, catalog: Catalog) -> MentionResult:
    courses = list(catalog.courses)
    result = MentionResult(mention)
    norm = normalize_text(mention)
    if not norm or not courses:
        return result

    def done(found: list[Course], group: bool = False) -> MentionResult | None:
        unique = list({c.id: c for c in found}.values())
        if not unique:
            return None
        result.courses = sorted(unique, key=lambda c: c.code)
        result.group = group
        result.ambiguous = len(unique) > 1 and not group
        return result

    # 1. Course code, or a bare course number
    code = normalize_course_code(mention)
    if code:
        return done([c for c in courses if c.code == code]) or result
    compact = norm.replace(' ', '')
    if compact.isdigit() and len(compact) in (3, 4):
        return done([c for c in courses if c.number == compact]) or result

    # 2. Exact title / alias
    if found := done([c for c in courses if norm in {normalize_text(n) for n in (c.title, *c.aliases)}]):
        return found

    # 3. Acronym (HCI, SDP2, "SDP II")
    if found := done([c for c in courses if compact in c.acronyms()]):
        return found

    # 4. Department prefix on its own
    if found := done([c for c in courses if c.prefix.lower() == compact], group=True):
        return found

    # 5. Every significant word of the mention appears in a title/alias
    words = _words(mention, _GENERIC_WORDS)
    if words:
        def contains(course: Course) -> bool:
            for name in (course.title, *course.aliases):
                name_words = _words(name)
                if all(any(nw == w or (len(w) >= 4 and nw.startswith(w)) for nw in name_words) for w in words):
                    return True
            return False
        if found := done([c for c in courses if contains(c)]):
            return found

    # 6. Fuzzy match for typos ("human computer interfase", "ethic and morality")
    scored: list[tuple[float, Course]] = []
    for course in courses:
        candidates = [normalize_text(n) for n in (course.title, *course.aliases)] + sorted(course.acronyms())
        best = max(difflib.SequenceMatcher(None, norm, cand).ratio() for cand in candidates)
        if best >= FUZZY_THRESHOLD:
            scored.append((best, course))
    if scored:
        scored.sort(key=lambda item: -item[0])
        top = scored[0][0]
        return done([c for score, c in scored if top - score < 0.04]) or result

    # 7. Multi-word mention where one word is a code/acronym/alias ("HCI CT", "cse415 lab"):
    #    accept only if every identifiable word points at the same single course.
    parts = [w for w in norm.split() if w not in _GENERIC_WORDS]
    if len(norm.split()) > 1 and parts and parts != norm.split():
        sub = [resolve_course_mention(w, catalog) for w in parts]
        found_ids = {c.id for r in sub if r.matched and not r.ambiguous for c in r.courses}
        if len(found_ids) == 1:
            return done([c for c in courses if c.id in found_ids]) or result

    return result


def resolve_courses(mentions: list[str], message: str, catalog: Catalog) -> CourseResolution:
    """Resolve the LLM's verbatim mentions plus any course codes literally present in the message."""
    resolution = CourseResolution()
    seen_codes: set[str] = set()
    for mention in mentions:
        result = resolve_course_mention(mention, catalog)
        resolution.results.append(result)
        if result.matched and len(result.courses) == 1:
            seen_codes.add(result.courses[0].code)
    for code in codes_in_text(message, {c.prefix for c in catalog.courses}):
        if code not in seen_codes and not any(normalize_course_code(m) == code for m in mentions):
            resolution.results.append(resolve_course_mention(code, catalog))
    return resolution


def scan_message_for_courses(message: str, catalog: Catalog) -> list[str]:
    """Fallback mention extraction when the LLM is unavailable: find codes, titles,
    aliases and acronyms that literally appear in the message."""
    norm = f' {normalize_text(message)} '
    mentions = codes_in_text(message, {c.prefix for c in catalog.courses})
    for course in catalog.courses:
        names = [course.title, *course.aliases]
        hits = [n for n in names if f' {normalize_text(n)} ' in norm]
        hits += [a for a in course.acronyms() if len(a) >= 2 and f' {a} ' in norm]
        if hits:
            mentions.append(max(hits, key=len))
    for prefix in {c.prefix.lower() for c in catalog.courses}:
        if f' {prefix} ' in norm and not any(m.lower().startswith(prefix) for m in mentions):
            mentions.append(prefix.upper())
    if not mentions:
        mentions = _residual_course_phrases(message, catalog)
    # A longer match absorbs shorter ones inside it ("Renamed Things" vs a course titled "Renamed").
    normalized = {m: f' {normalize_text(m)} ' for m in mentions}
    mentions = [m for m in mentions
                if not any(o != m and normalized[m] in normalized[o] and len(normalized[o]) > len(normalized[m])
                           for o in mentions)]
    return list(dict.fromkeys(mentions))


# Words that never name a course in a student question (used only by the no-LLM fallback).
_QUESTION_WORDS = set("""
a about after again all an and any anything are at be before by can coming could course courses date day days
do does exam exams for from give happening has have how i in info information is it its left let list me my
need next of on or our please remaining rest schedule scheduled show so tell than that the their them there
these this those to today tomorrow upcoming update updates us we week weekly what whats when where which who
will with you your time syllabus topics topic portion chapter chapters venue room teacher faculty sir madam
mam miss link notes note section sec ct cts class test tests mid midterm quiz lab project presentation
evaluation online last previous past recent first second third one two three yet any know want
sunday monday tuesday wednesday thursday friday saturday january february march april may june july august
september october november december jan feb mar apr jun jul aug sep sept oct nov dec held going ok okay
""".split())
_COURSE_CUE_RE = r'(?:\b(?:of|for|in)\s+{p}\b|\b{p}\s+(?:exam|exams|ct|cts|class|test|mid|lab|project|quiz|syllabus|course))'


def _residual_course_phrases(message: str, catalog: Catalog) -> list[str]:
    """Content words left after removing question vocabulary, grouped into phrases.
    A phrase counts as a course mention if it resolves to a course, or if it sits in a
    course-like position ("of X", "X exam") so an unknown course is reported, not ignored."""
    norm = normalize_text(message)
    phrases, current = [], []
    for word in norm.split():
        if word in _QUESTION_WORDS or word.isdigit() or len(word) < 2:
            if current:
                phrases.append(' '.join(current))
                current = []
        else:
            current.append(word)
    if current:
        phrases.append(' '.join(current))

    mentions = []
    for phrase in phrases:
        if resolve_faculty_mention(phrase, catalog).faculty:
            continue  # "of Nafisa madam" names a teacher, not a course
        if resolve_course_mention(phrase, catalog).matched or re.search(_COURSE_CUE_RE.format(p=re.escape(phrase)), norm):
            mentions.append(phrase)
    return mentions


@dataclass
class FacultyResolution:
    mention: str
    faculty: list[Faculty] = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return len(self.faculty) > 1


def resolve_faculty_mention(mention: str, catalog: Catalog) -> FacultyResolution:
    result = FacultyResolution(mention)
    words = [w for w in normalize_text(mention).split() if w not in _HONORIFIC_WORDS]
    if not words:
        return result
    people = catalog.all_faculty()

    def name_words(member: Faculty) -> list[str]:
        return [w for w in normalize_text(member.name).split() if w not in _HONORIFIC_WORDS]

    exact = [m for m in people if all(w in name_words(m) for w in words)]
    if exact:
        result.faculty = exact
        return result

    fuzzy = [
        m for m in people
        if all(any(difflib.SequenceMatcher(None, w, nw).ratio() >= 0.8 for nw in name_words(m)) for w in words)
    ]
    result.faculty = fuzzy
    return result
