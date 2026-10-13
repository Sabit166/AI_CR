// Mirrors academic.py and public.normalize_course_code / course_type_for_code.
// The server re-validates everything; this only gives instant feedback while typing.

const INPUT_CODE_RE = /^\s*([A-Za-z]{2,5})[\s_-]*([0-9]{3,4})\s*$/

export const FACULTY_RULES = {
  Theoretical: { min: 2, max: 2 },
  Sessional: { min: 3, max: 4 },
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
    parity: lastDigit % 2 === 0 ? 'even' : 'odd',
    number,
    error: null,
  }
}

export function facultyCountHint(courseType, count, rules = FACULTY_RULES) {
  const rule = rules[courseType]
  if (!rule) return null
  const expected = rule.min === rule.max ? `${rule.min}` : `${rule.min} or ${rule.max}`
  return {
    ok: count >= rule.min && count <= rule.max,
    text: `${courseType} courses normally have ${expected} faculty members.`,
  }
}
