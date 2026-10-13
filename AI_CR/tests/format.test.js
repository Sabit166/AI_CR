import assert from 'node:assert/strict'
import { test } from 'node:test'
import { daysFrom, groupByWeek, isSafeLink, relativeDayBadge, weekLabel } from '../src/lib/format.js'

// 2026-10-13 is a Tuesday.
test('weekLabel uses Sunday-start academic weeks', () => {
  assert.equal(weekLabel('2026-10-13', '2026-10-15'), 'This week') // Thursday
  assert.equal(weekLabel('2026-10-13', '2026-10-18'), 'Next week') // Sunday
  assert.equal(weekLabel('2026-10-13', '2026-10-22'), 'Next week') // Thursday
  assert.equal(weekLabel('2026-10-13', '2026-10-25'), 'Later')
  // On Friday the Sunday-Thursday ahead is next week, matching the Messenger bot.
  assert.equal(weekLabel('2026-10-16', '2026-10-18'), 'Next week')
})

test('daysFrom and relative badges ignore the viewer timezone', () => {
  assert.equal(daysFrom('2026-10-13', '2026-10-13'), 0)
  assert.equal(daysFrom('2026-12-31', '2027-01-01'), 1)
  assert.equal(relativeDayBadge('2026-10-13', '2026-10-13'), 'Today')
  assert.equal(relativeDayBadge('2026-10-13', '2026-10-14'), 'Tomorrow')
  assert.equal(relativeDayBadge('2026-10-13', '2026-10-16'), 'In 3 days')
  assert.equal(relativeDayBadge('2026-10-13', '2026-10-30'), null)
})

test('groupByWeek keeps order and groups days', () => {
  const exams = ['2026-10-14', '2026-10-14', '2026-10-19', '2026-11-02'].map((exam_date, id) => ({ id, exam_date }))
  const weeks = groupByWeek(exams, '2026-10-13')
  assert.deepEqual(weeks.map((w) => w.label), ['This week', 'Next week', 'Later'])
  assert.equal(weeks[0].days[0].items.length, 2)
})

test('isSafeLink only allows http(s) URLs', () => {
  assert.equal(isSafeLink('https://drive.google.com/x'), true)
  assert.equal(isSafeLink('javascript:alert(1)'), false)
  assert.equal(isSafeLink(null), false)
})
