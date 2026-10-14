// Choices for the exam form's date and time dropdowns, so the CR picks instead of typing.
// Dates are Dhaka-local ISO dates ("2026-10-20") and are computed in UTC so the
// viewer's own timezone can never shift a day.

const DAY_MS = 86400000

function isoToUtc(iso) {
  return Date.parse(`${iso}T00:00:00Z`)
}

function utcToIso(time) {
  return new Date(time).toISOString().slice(0, 10)
}

const dayLabel = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
const monthLabel = new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })

/**
 * Days from `pastDays` before `today` to `futureDays` after it, grouped by month:
 * [{ label: 'October 2026', options: [{ value: '2026-10-14', label: 'Wed 14 Oct · Today' }, …] }, …]
 * `include` (e.g. the date of an exam being edited) is always offered, even outside the range.
 */
export function dateOptions(today, { pastDays = 14, futureDays = 180, include = '' } = {}) {
  const start = isoToUtc(today)
  const days = []
  for (let offset = -pastDays; offset <= futureDays; offset += 1) days.push(start + offset * DAY_MS)
  const extra = include ? isoToUtc(include) : NaN
  if (!Number.isNaN(extra) && !days.includes(extra)) days.push(extra)
  days.sort((a, b) => a - b)

  const groups = []
  for (const time of days) {
    const offset = Math.round((time - start) / DAY_MS)
    const relative = offset === 0 ? ' · Today' : offset === 1 ? ' · Tomorrow' : ''
    const option = { value: utcToIso(time), label: `${dayLabel.format(time)}${relative}` }
    const label = monthLabel.format(time)
    const last = groups.at(-1)
    if (last && last.label === label) last.options.push(option)
    else groups.push({ label, options: [option] })
  }
  return groups
}

const pad = (n) => String(n).padStart(2, '0')

function hourLabel(hour) {
  const suffix = hour < 12 ? 'AM' : 'PM'
  return `${hour % 12 === 0 ? 12 : hour % 12} ${suffix}`
}

/** 7 AM – 11 PM (plus `include`'s hour if it falls outside): [{ value: '08', label: '8 AM' }, …] */
export function hourOptions(include = '') {
  const hours = []
  for (let h = 7; h <= 23; h += 1) hours.push(h)
  const extra = include ? Number(include.slice(0, 2)) : NaN
  if (Number.isInteger(extra) && !hours.includes(extra)) hours.push(extra)
  return hours.sort((a, b) => a - b).map((h) => ({ value: pad(h), label: hourLabel(h) }))
}

/** Every 5 minutes (plus `include`'s minute if it is off that grid): [{ value: '05', label: ':05' }, …] */
export function minuteOptions(include = '') {
  const minutes = []
  for (let m = 0; m < 60; m += 5) minutes.push(m)
  const extra = include ? Number(include.slice(3, 5)) : NaN
  if (Number.isInteger(extra) && !minutes.includes(extra)) minutes.push(extra)
  return minutes.sort((a, b) => a - b).map((m) => ({ value: pad(m), label: `:${pad(m)}` }))
}

/** '09:40' -> { hour: '09', minute: '40' }; '' -> { hour: '', minute: '' } */
export function splitTime(value) {
  if (!value) return { hour: '', minute: '' }
  return { hour: value.slice(0, 2), minute: value.slice(3, 5) }
}

/** No hour means no time; an hour without minutes means on the hour. */
export function joinTime(hour, minute) {
  return hour ? `${hour}:${minute || '00'}` : ''
}
