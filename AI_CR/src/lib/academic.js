// Mirrors academic.py and public.normalize_course_code / course_type_for_code.
// The server re-validates everything; this only gives instant feedback while typing.

const INPUT_CODE_RE = /^\s*([A-Za-z]{2,5})[\s_-]*([0-9]{3,4})\s*$/

// Every Theoretical course runs as two course sections with one course teacher each
// (the same teacher may take both). Course sections are not class sections.
export const COURSE_SECTIONS = ['A', 'B']

export function parseCourseCode(raw) {
  const text = (raw ?? '').trim()
  if (!text) return { code: null, courseType: null, error: 'Course code is required.' }
  const match = INPUT_CODE_RE.exec(text)
  if (!match) {
    return {
      code: null,
      courseType: null,
      error: 'Use letters followed by a 3–4 digit number, e.g. CSE-415.',
    }
  }
  const number = match[2]
  const code = `${match[1].toUpperCase()}-${number}`
  const lastDigit = Number(number.at(-1))
  return {
    code,
    courseType: lastDigit % 2 === 0 ? 'Sessional' : 'Theoretical',
    error: null,
  }
}

/** Course sections still missing a teacher, e.g. ['B']. */
export function missingSections(sectionFaculty) {
  return COURSE_SECTIONS.filter((section) => !sectionFaculty?.[section])
}

/** Class sections are for Sessional exams only. */
export function hasSections(courseType) {
  return courseType === 'Sessional'
}

/** Theoretical courses have course sections A and B; their exams sit both at one time. */
export function hasCourseSections(courseType) {
  return courseType === 'Theoretical'
}
