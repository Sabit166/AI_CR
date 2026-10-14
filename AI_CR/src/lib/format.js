// Display helpers shared by the CR dashboard and the student board.
// Exam dates arrive as Dhaka-local ISO dates ("2026-10-20"); they are never shifted by the viewer's timezone.

const DAY_MS = 86400000

export function formatDay(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

export function formatTime(value) {
  if (!value) return null
  const [h, m] = value.split(':').map(Number)
  return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function groupByDay(exams) {
  const groups = []
  for (const exam of exams) {
    const last = groups.at(-1)
    if (last && last.day === exam.exam_date) last.items.push(exam)
    else groups.push({ day: exam.exam_date, items: [exam] })
  }
  return groups
}

function utcDay(iso) {
  return Date.parse(`${iso}T00:00:00Z`)
}

/** Whole days from `today` to `iso` (both ISO dates). */
export function daysFrom(today, iso) {
  return Math.round((utcDay(iso) - utcDay(today)) / DAY_MS)
}

function sundayOf(iso) {
  const time = utcDay(iso)
  return time - new Date(time).getUTCDay() * DAY_MS
}

/** "This week" / "Next week" / "Later" — academic weeks start on Sunday. */
export function weekLabel(today, iso) {
  const weeks = Math.round((sundayOf(iso) - sundayOf(today)) / (7 * DAY_MS))
  if (weeks <= 0) return 'This week'
  if (weeks === 1) return 'Next week'
  return 'Later'
}

/** Day groups bucketed under week headings, preserving order. */
export function groupByWeek(exams, today) {
  const weeks = []
  for (const group of groupByDay(exams)) {
    const label = weekLabel(today, group.day)
    const last = weeks.at(-1)
    if (last && last.label === label) last.days.push(group)
    else weeks.push({ label, days: [group] })
  }
  return weeks
}

export function relativeDayBadge(today, iso) {
  const days = daysFrom(today, iso)
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  if (days > 1 && days < 7) return `In ${days} days`
  return null
}

/** 'Section B' (class or course section), 'Sections A & B' (Theoretical, both) or 'Whole class'. */
export function sectionText(exam) {
  if (exam.section) return `Section ${exam.section}`
  if (exam.course_section) return `Section ${exam.course_section}`
  return exam.course_type === 'Theoretical' ? 'Sections A & B' : 'Whole class'
}

/** 'Section A: X · Section B: Y' when the sections have different teachers, else the names. */
export function facultyText(exam) {
  // Per-section teachers, unless the exam carries its own (pre-course-section) faculty picks.
  const bySection = exam.faculty_source === 'exam' ? [] : (exam.section_faculty ?? [])
  if (bySection.length > 1 && new Set(bySection.map((item) => item.name)).size > 1) {
    return bySection.map((item) => `Section ${item.section}: ${item.name}`).join(' · ')
  }
  return (exam.faculty_names ?? []).join(', ')
}

export function isSafeLink(url) {
  return typeof url === 'string' && /^https?:\/\/\S+$/i.test(url)
}
