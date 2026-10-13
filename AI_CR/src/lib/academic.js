// Mirrors academic.py and public.normalize_course_code / course_type_for_code.
// The server re-validates everything; this only gives instant feedback while typing.

const INPUT_CODE_RE = /^\s*([A-Za-z]{2,5})[\s_-]*([0-9]{3,4})\s*$/

// Theoretical courses always have exactly two course teachers; Sessional is up to the CR (max null = no limit).
export const FACULTY_RULES = {
  Theoretical: { min: 2, max: 2 },
  Sessional: { min: 0, max: null },
}

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

export function facultyCountHint(courseType, count, rules = FACULTY_RULES) {
  const rule = rules[courseType]
  if (!rule) return null
  const ok = count >= rule.min && (rule.max == null || count <= rule.max)
  if (rule.max == null) return { ok, text: 'Select every teacher who takes this course.' }
  const expected = rule.min === rule.max ? `exactly ${rule.min}` : `${rule.min} to ${rule.max}`
  return { ok, text: `${courseType} courses have ${expected} course teachers.` }
}

/** Theoretical exams (CTs, Mid) are held for every section on the same day. */
export function hasSections(courseType) {
  return courseType === 'Sessional'
}
