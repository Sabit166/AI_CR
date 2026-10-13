// Mobile-first UI end-to-end test (real backend + isolated Docker DB, fake Supabase Auth).
//
//   docker compose -f tests/db/docker-compose.yml up -d --wait     (repo root)
//   python tests/e2e/server.py                                      (repo root, port 8011)
//   npm run e2e:build && npm run e2e:preview                        (this folder, port 4179)
//   npm run e2e                                                     (this folder)
//
// Uses the locally installed Chrome via playwright-core (no browser download).
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const APP = 'http://127.0.0.1:4179'
const SHOTS = process.env.E2E_SCREENSHOTS ?? 'e2e/screenshots'
mkdirSync(SHOTS, { recursive: true })

const VIEWPORTS = [
  { name: 'small-phone', width: 360, height: 740, isMobile: true },
  { name: 'large-phone', width: 430, height: 932, isMobile: true },
  { name: 'tablet', width: 768, height: 1024, isMobile: true },
  { name: 'desktop', width: 1280, height: 800, isMobile: false },
]

// An exam date a few days ahead, so it lands on the first page of "Upcoming".
const soon = new Date(Date.now() + 9 * 86400000).toISOString().slice(0, 10)
const prefix = Array.from({ length: 4 }, () => String.fromCharCode(65 + Math.floor(Math.random() * 26))).join('')
const results = []

function fakeJwt(email) {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url')
  return `${b64({ alg: 'none', typ: 'JWT' })}.${b64({ sub: email, email, exp: 4102444800, role: 'authenticated', aud: 'authenticated' })}.sig`
}

async function fakeSupabaseAuth(page) {
  await page.route('**/auth/v1/**', async (route) => {
    const url = route.request().url()
    if (url.includes('/token')) {
      const body = JSON.parse(route.request().postData() ?? '{}')
      if (body.password !== 'correct-password') {
        return route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ code: 'invalid_credentials', error_code: 'invalid_credentials', msg: 'Invalid login credentials' }),
        })
      }
      const email = body.email
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: fakeJwt(email),
          token_type: 'bearer',
          expires_in: 3600,
          expires_at: Math.floor(Date.now() / 1000) + 3600,
          refresh_token: 'refresh',
          user: {
            id: email === 'cr@e2e.test' ? '44444444-4444-4444-4444-444444444444' : '55555555-5555-5555-5555-555555555555',
            email,
            aud: 'authenticated',
            role: 'authenticated',
            app_metadata: {},
            user_metadata: {},
            created_at: new Date().toISOString(),
          },
        }),
      })
    }
    if (url.includes('/logout')) return route.fulfill({ status: 204, body: '' })
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

async function signIn(page, email = 'cr@e2e.test', password = 'correct-password') {
  await page.goto(`${APP}/cr/`)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function step(name, fn) {
  try {
    await fn()
    results.push(['PASS', name])
    console.log(`PASS  ${name}`)
  } catch (error) {
    results.push(['FAIL', name, error.message])
    console.log(`FAIL  ${name}\n      ${error.message.split('\n').slice(0, 6).join('\n      ')}`)
  }
}

async function noHorizontalOverflow(page) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  assert.ok(scrollWidth <= innerWidth, `horizontal overflow: scrollWidth ${scrollWidth} > ${innerWidth}`)
}

async function smallTouchTargets(page) {
  return page.evaluate(() => {
    const bad = []
    const selector = 'button, a.btn, select, input:not([type=checkbox]):not([type=radio]), textarea, summary, .chip, .check'
    for (const el of document.querySelectorAll(selector)) {
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      if (el.closest('.visually-hidden') || el.classList.contains('toast-close')) continue
      if (r.height < 44) {
        const label = (el.textContent || el.getAttribute('aria-label') || el.id || '').trim().slice(0, 24)
        bad.push(`${el.tagName.toLowerCase()} "${label}" h=${Math.round(r.height)}`)
      }
    }
    return bad
  })
}

function nav(page, tab) {
  return page.getByRole('button', { name: new RegExp(`^(\\S+\\s)?${tab}$`) }).filter({ visible: true }).first()
}

async function examTypeValues(page) {
  return page.getByRole('group', { name: /Exam type/ }).getByRole('radio').evaluateAll((els) => els.map((e) => e.value))
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })

// ---------------------------------------------------------------- full CR flow on a small phone
{
  const context = await browser.newContext({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  const page = await context.newPage()
  await fakeSupabaseAuth(page)
  const apiCalls = []
  page.on('request', (req) => {
    if (req.url().includes(':8011/api/')) apiCalls.push(`${req.method()} ${new URL(req.url()).pathname}`)
  })

  await step('wrong password shows an inline error', async () => {
    await signIn(page, 'cr@e2e.test', 'nope')
    await page.getByText('Wrong email or password.').waitFor({ timeout: 5000 })
  })

  await step('CR signs in and lands on Exams', async () => {
    await page.getByLabel('Password').fill('correct-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await page.getByRole('heading', { name: 'Exams', level: 1 }).waitFor({ timeout: 5000 })
    await page.screenshot({ path: `${SHOTS}/01-exams-360.png`, fullPage: true })
  })

  await step('course code drives the derived course type and validation', async () => {
    await nav(page, 'Courses').click()
    await page.getByRole('button', { name: '+ Add course' }).click()
    const code = page.getByLabel(/Course code/)
    await code.fill(`${prefix.toLowerCase()} 415`)
    await page.locator('#course-type-derived').getByText('Theoretical').waitFor()
    await code.fill(`${prefix}-416`)
    await page.locator('#course-type-derived').getByText('Sessional').waitFor()
    await code.fill(`${prefix}-41A`)
    await code.blur()
    await page.getByText('Use letters followed by a 3–4 digit number').waitFor()
    assert.equal(await page.getByText(/odd|even/i).count(), 0, 'no odd/even explanation on the site')
    await page.screenshot({ path: `${SHOTS}/02-course-invalid-360.png`, fullPage: true })
  })

  await step('theory course: faculty count rule, inline faculty add, save', async () => {
    await page.getByLabel(/Course code/).fill(`${prefix}-415`)
    await page.getByLabel(/Course title/).fill(`Interaction Design ${prefix}`)
    await page.getByLabel('Short names students use').fill(`IDX${prefix}`)
    for (const name of [`Ayesha ${prefix}`, `Rahim ${prefix}`, `Karim ${prefix}`]) {
      await page.getByPlaceholder('Add a faculty member').fill(name)
      await page.getByRole('button', { name: 'Add', exact: true }).click()
      await page.getByRole('checkbox', { name }).waitFor()
      assert.ok(await page.getByRole('checkbox', { name }).isChecked(), 'new faculty auto-selected')
    }
    await page.getByRole('button', { name: 'Add course' }).click()
    await page.getByText('Theoretical courses have exactly 2 course teachers. You selected 3.').waitFor()
    await page.getByRole('checkbox', { name: `Karim ${prefix}` }).uncheck()
    await page.getByRole('button', { name: 'Add course' }).click()
    await page.getByText(`Added ${prefix}-415.`).waitFor()
    await page.getByText(`Interaction Design ${prefix}`, { exact: true }).waitFor()
  })

  await step('sessional course with 3 faculty', async () => {
    await page.getByRole('button', { name: '+ Add course' }).click()
    await page.getByLabel(/Course code/).fill(`${prefix}-416`)
    await page.getByLabel(/Course title/).fill(`Interaction Design Lab ${prefix}`)
    for (const name of [`Ayesha ${prefix}`, `Rahim ${prefix}`, `Karim ${prefix}`]) await page.getByRole('checkbox', { name }).check()
    await page.getByRole('button', { name: 'Add course' }).click()
    await page.getByText(`Added ${prefix}-416.`).waitFor()
    await page.screenshot({ path: `${SHOTS}/03-courses-360.png`, fullPage: true })
  })

  await step('duplicate course in the same term is rejected by the server, input kept', async () => {
    await page.getByRole('button', { name: '+ Add course' }).click()
    await page.getByLabel(/Course code/).fill(`${prefix.toLowerCase()}415`)
    await page.getByLabel(/Course title/).fill('Duplicate')
    for (const name of [`Ayesha ${prefix}`, `Rahim ${prefix}`]) await page.getByRole('checkbox', { name }).check()
    await page.getByRole('button', { name: 'Add course' }).click()
    await page.getByText(`${prefix}-415 is already configured`).waitFor()
    assert.equal(await page.getByLabel(/Course title/).inputValue(), 'Duplicate')
    await page.getByRole('button', { name: 'Cancel' }).click()
  })

  await step('exam form: course selection fills title, faculty and allowed exam types', async () => {
    await nav(page, 'Exams').click()
    await page.getByRole('button', { name: '+ New exam' }).click()
    await page.getByRole('radio', { name: new RegExp(`${prefix}-415`) }).check()
    await page.locator('.readonly-value').getByText(`Interaction Design ${prefix}`).waitFor()
    assert.deepEqual(await examTypeValues(page), ['CT 1', 'CT 2', 'Mid', 'CT 3'])
    assert.equal(await page.locator('#exam-section').count(), 0, 'Theoretical exams have no section')
    assert.equal(await page.getByRole('group', { name: /Faculty for this exam/ }).getByRole('checkbox').count(), 2)

    await page.getByRole('radio', { name: 'CT 2' }).check()
    await page.getByRole('checkbox', { name: `Rahim ${prefix}` }).check()
    await page.getByRole('radio', { name: new RegExp(`${prefix}-416`) }).check()
    assert.deepEqual(await examTypeValues(page), ['Project Update', 'Evaluation', 'Online Exam', 'Project Presentation', 'Lab Test'])
    await page.locator('#exam-section').waitFor()
    assert.equal(await page.getByRole('radio', { name: 'CT 2' }).count(), 0)
    assert.equal(await page.getByRole('group', { name: /Faculty for this exam/ }).getByRole('checkbox').count(), 3)
    assert.ok(await page.getByRole('checkbox', { name: `Rahim ${prefix}` }).isChecked(), 'teacher shared by both courses stays ticked')
    await page.locator('.readonly-value').getByText(`Interaction Design Lab ${prefix}`).waitFor()
    await page.screenshot({ path: `${SHOTS}/04-exam-form-360.png`, fullPage: true })
  })

  await step('validation errors keep the entered values', async () => {
    await page.getByRole('radio', { name: 'Lab Test' }).check()
    await page.getByLabel('Syllabus').fill('Experiment 1\nExperiment 2')
    await page.getByRole('button', { name: 'Save exam' }).click()
    await page.getByText('Pick the exam date.').waitFor()
    assert.equal(await page.getByLabel('Syllabus').inputValue(), 'Experiment 1\nExperiment 2')
  })

  await step('server/network failure keeps the form and says so', async () => {
    await page.getByLabel(/^Date/).fill(soon)
    await page.route('**/api/exams', (route) => (route.request().method() === 'POST' ? route.abort() : route.continue()))
    await page.getByRole('button', { name: 'Save exam' }).click()
    await page.getByText('Could not reach the server', { exact: false }).waitFor()
    assert.equal(await page.getByLabel('Syllabus').inputValue(), 'Experiment 1\nExperiment 2')
    await page.unroute('**/api/exams')
  })

  await step('preview shows the student-facing text', async () => {
    await page.getByRole('button', { name: 'Preview' }).click()
    await page.locator('.preview pre').waitFor()
    const text = await page.locator('.preview pre').textContent()
    assert.match(text, new RegExp(`${prefix}-416 · Interaction Design Lab ${prefix}`))
    assert.match(text, /Experiment 1\nExperiment 2/)
  })

  await step('double-tapping save creates exactly one exam', async () => {
    const before = apiCalls.filter((c) => c === 'POST /api/exams').length
    await page.getByRole('button', { name: 'Save exam' }).dblclick()
    await page.getByText(`Saved ${prefix}-416 Lab Test.`).waitFor()
    const posts = apiCalls.filter((c) => c === 'POST /api/exams').length - before
    assert.ok(posts <= 1, `expected at most one POST, saw ${posts}`)
    const count = await page.evaluate(async (p) => {
      const key = Object.keys(localStorage).find((k) => k.includes('auth-token'))
      const token = JSON.parse(localStorage.getItem(key)).access_token
      const r = await fetch('http://127.0.0.1:8011/api/exams?scope=upcoming&limit=100', { headers: { Authorization: `Bearer ${token}` } })
      return (await r.json()).exams.filter((e) => e.course_code === `${p}-416`).length
    }, prefix)
    assert.equal(count, 1)
    await page.locator('.exam-card', { hasText: `${prefix}-416` }).waitFor()
    await page.screenshot({ path: `${SHOTS}/05-exam-list-360.png`, fullPage: true })
  })

  await step('edit an exam', async () => {
    await page.locator('.exam-card', { hasText: `${prefix}-416` }).getByRole('button', { name: 'Edit' }).click()
    assert.equal(await page.getByLabel('Syllabus').inputValue(), 'Experiment 1\nExperiment 2')
    await page.getByLabel(/^Time/).fill('14:30')
    await page.getByRole('button', { name: 'Save changes' }).click()
    await page.getByText(`Updated ${prefix}-416 Lab Test.`).waitFor()
    await page.locator('.exam-card', { hasText: `${prefix}-416` }).getByText(/2:30/).waitFor()
  })

  await step('student board shows the exam read-only, without signing in', async () => {
    const studentContext = await browser.newContext({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true })
    const student = await studentContext.newPage()
    const requests = []
    student.on('request', (request) => requests.push(new URL(request.url()).pathname))
    await student.goto(APP)
    await student.getByRole('heading', { name: 'Upcoming exams', level: 1 }).waitFor({ timeout: 5000 })
    const card = student.locator('.exam-card', { hasText: `${prefix}-416` })
    await card.waitFor()
    await card.getByText('Experiment 1').waitFor()
    await card.getByText(/2:30/).waitFor()
    assert.equal(await student.getByRole('button', { name: /Edit|Delete|New exam|Sign out/ }).count(), 0)
    assert.equal(await student.locator('input, textarea').count(), 0)
    assert.equal(await student.getByLabel('Email').count(), 0)
    const href = await student.getByRole('link', { name: /Ask on Messenger/ }).first().getAttribute('href')
    assert.match(href, /^https:\/\/m\.me\//)

    await student.getByLabel('Course').selectOption(await student.locator('option', { hasText: `${prefix}-415` }).getAttribute('value'))
    await student.getByText('No upcoming exams posted').waitFor()
    await student.getByLabel('Course').selectOption(await student.locator('option', { hasText: `${prefix}-416` }).getAttribute('value'))
    await student.locator('.exam-card', { hasText: `${prefix}-416` }).waitFor()

    const api = requests.filter((path) => path.startsWith('/api/') || path.startsWith('/auth/'))
    assert.ok(api.length > 0 && api.every((path) => path.startsWith('/api/public/')), `unexpected calls: ${api}`)
    await noHorizontalOverflow(student)
    assert.deepEqual(await smallTouchTargets(student), [], 'small touch targets')
    await student.screenshot({ path: `${SHOTS}/07-student-board-360.png`, fullPage: true })
    await studentContext.close()
  })

  await step('removing a course with exams explains it will be archived', async () => {
    await nav(page, 'Courses').click()
    await page.locator('.course-card', { hasText: `${prefix}-416` }).getByRole('button', { name: 'Remove' }).click()
    await page.getByRole('dialog').getByText('those records are kept').waitFor()
    await page.screenshot({ path: `${SHOTS}/06-confirm-360.png` })
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
  })

  await step('delete exam requires confirmation', async () => {
    await nav(page, 'Exams').click()
    await page.locator('.exam-card', { hasText: `${prefix}-416` }).getByRole('button', { name: 'Delete' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
    await page.getByText(`Deleted ${prefix}-416 Lab Test.`).waitFor()
    assert.equal(await page.locator('.exam-card', { hasText: `${prefix}-416` }).count(), 0)
  })

  await step('unsaved draft survives a reload', async () => {
    await page.getByRole('button', { name: '+ New exam' }).click()
    await page.getByRole('radio', { name: new RegExp(`${prefix}-415`) }).check()
    await page.getByLabel('Syllabus').fill('Draft text')
    await page.reload()
    await page.getByRole('button', { name: '+ New exam' }).click()
    await page.getByText('Restored your unsaved entry.').waitFor()
    assert.equal(await page.getByLabel('Syllabus').inputValue(), 'Draft text')
    await page.getByRole('button', { name: 'Cancel' }).click()
  })

  await context.close()
}

// ---------------------------------------------------------------- non-CR account
await step('signed-in non-CR account is refused', async () => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  const page = await context.newPage()
  await fakeSupabaseAuth(page)
  await signIn(page, 'student@e2e.test')
  await page.getByRole('heading', { name: 'Not a CR account' }).waitFor({ timeout: 5000 })
  await context.close()
})

// ---------------------------------------------------------------- layout at every viewport
for (const vp of VIEWPORTS) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.isMobile, hasTouch: vp.isMobile })
  const page = await context.newPage()
  await fakeSupabaseAuth(page)
  await signIn(page)
  await page.getByRole('heading', { name: 'Exams', level: 1 }).waitFor({ timeout: 5000 })

  for (const tab of ['Exams', 'Courses', 'Faculty']) {
    await step(`${vp.name} ${vp.width}px ${tab}: no horizontal overflow${vp.isMobile ? ', touch targets >= 44px' : ''}`, async () => {
      await nav(page, tab).click()
      await page.getByRole('heading', { name: tab, level: 1 }).waitFor()
      await noHorizontalOverflow(page)
      if (vp.isMobile) assert.deepEqual(await smallTouchTargets(page), [], 'small touch targets')
      await page.screenshot({ path: `${SHOTS}/layout-${vp.name}-${tab.toLowerCase()}.png`, fullPage: true })
    })
  }
  await step(`${vp.name} ${vp.width}px exam form fits`, async () => {
    await nav(page, 'Exams').click()
    await page.getByRole('button', { name: '+ New exam' }).click()
    await page.getByRole('radio', { name: new RegExp(`${prefix}-415`) }).check()
    await noHorizontalOverflow(page)
    if (vp.isMobile) assert.deepEqual(await smallTouchTargets(page), [], 'small touch targets')
    await page.screenshot({ path: `${SHOTS}/layout-${vp.name}-exam-form.png`, fullPage: true })
  })
  await context.close()
}

// ---------------------------------------------------------------- student board at every viewport
for (const vp of VIEWPORTS) {
  await step(`${vp.name} ${vp.width}px student board: no horizontal overflow${vp.isMobile ? ', touch targets >= 44px' : ''}`, async () => {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.isMobile, hasTouch: vp.isMobile })
    const page = await context.newPage()
    await page.goto(APP)
    await page.getByRole('heading', { name: 'Upcoming exams', level: 1 }).waitFor({ timeout: 5000 })
    await page.getByRole('tab', { name: 'Past' }).click()
    await page.getByRole('heading', { name: 'Past exams', level: 1 }).waitFor()
    await page.getByRole('tab', { name: 'Upcoming' }).click()
    await page.getByRole('heading', { name: 'Upcoming exams', level: 1 }).waitFor()
    await noHorizontalOverflow(page)
    if (vp.isMobile) assert.deepEqual(await smallTouchTargets(page), [], 'small touch targets')
    await page.screenshot({ path: `${SHOTS}/layout-${vp.name}-student.png`, fullPage: true })
    await context.close()
  })
}

await browser.close()

const failed = results.filter((r) => r[0] === 'FAIL')
console.log(`\n${results.length - failed.length} passed, ${failed.length} failed`)
process.exit(failed.length ? 1 : 0)
