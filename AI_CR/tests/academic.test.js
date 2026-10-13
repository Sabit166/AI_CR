// Run with: node --test tests/
// Same vectors as tests/test_academic.py (Python) and the SQL parity test.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseCourseCode, facultyCountHint, hasSections } from '../src/lib/academic.js'

const VECTORS = [
  ['CSE-415', 'CSE-415', 'Theoretical'],
  ['cse 415', 'CSE-415', 'Theoretical'],
  ['CSE415', 'CSE-415', 'Theoretical'],
  ['cse_464', 'CSE-464', 'Sessional'],
  ['GEEM 433', 'GEEM-433', 'Theoretical'],
  [' eee-2100 ', 'EEE-2100', 'Sessional'],
  ['CSE-410', 'CSE-410', 'Sessional'],
  ['MATH-1001', 'MATH-1001', 'Theoretical'],
  ['CSE-415A', null, null],
  ['415', null, null],
  ['C-415', null, null],
  ['CSE-41', null, null],
  ['CSE-41500', null, null],
  ['CS E-415', null, null],
  ['', null, null],
]

for (const [raw, code, courseType] of VECTORS) {
  test(`parseCourseCode(${JSON.stringify(raw)})`, () => {
    const parsed = parseCourseCode(raw)
    assert.equal(parsed.code, code)
    assert.equal(parsed.courseType, courseType)
    assert.equal(parsed.error === null, code !== null)
  })
}

test('faculty count hints', () => {
  assert.equal(facultyCountHint('Theoretical', 2).ok, true)
  assert.equal(facultyCountHint('Theoretical', 3).ok, false)
  assert.equal(facultyCountHint('Theoretical', 0).ok, false)
  for (const count of [0, 1, 2, 4, 7]) assert.equal(facultyCountHint('Sessional', count).ok, true)
  assert.match(facultyCountHint('Theoretical', 1).text, /exactly 2/)
})

test('only Sessional exams have sections', () => {
  assert.equal(hasSections('Sessional'), true)
  assert.equal(hasSections('Theoretical'), false)
})
