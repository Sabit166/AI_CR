import { test } from 'node:test'
import assert from 'node:assert/strict'
import { dateOptions, hourOptions, joinTime, minuteOptions, splitTime } from '../src/lib/pickers.js'

test('date options are grouped by month and labelled', () => {
  const groups = dateOptions('2026-10-30', { pastDays: 1, futureDays: 3 })
  assert.deepEqual(
    groups.map((g) => [g.label, g.options.map((o) => o.value)]),
    [
      ['October 2026', ['2026-10-29', '2026-10-30', '2026-10-31']],
      ['November 2026', ['2026-11-01', '2026-11-02']],
    ],
  )
  assert.equal(groups[0].options[1].label, 'Fri 30 Oct · Today')
  assert.equal(groups[0].options[2].label, 'Sat 31 Oct · Tomorrow')
})

test('a date outside the range is still offered (editing an old exam)', () => {
  const values = dateOptions('2026-10-14', { pastDays: 0, futureDays: 1, include: '2026-01-05' }).flatMap((g) =>
    g.options.map((o) => o.value),
  )
  assert.deepEqual(values, ['2026-01-05', '2026-10-14', '2026-10-15'])
})

test('hour and minute options', () => {
  const hours = hourOptions()
  assert.equal(hours[0].label, '7 AM')
  assert.equal(hours.find((h) => h.value === '12').label, '12 PM')
  assert.equal(hours.at(-1).label, '11 PM')
  assert.ok(hourOptions('05:30').some((h) => h.value === '05' && h.label === '5 AM'))
  assert.equal(minuteOptions().length, 12)
  assert.ok(minuteOptions('09:42').some((m) => m.value === '42'))
})

test('time split and join', () => {
  assert.deepEqual(splitTime('09:40'), { hour: '09', minute: '40' })
  assert.deepEqual(splitTime(''), { hour: '', minute: '' })
  assert.equal(joinTime('14', '05'), '14:05')
  assert.equal(joinTime('14', ''), '14:00')
  assert.equal(joinTime('', '30'), '')
})
