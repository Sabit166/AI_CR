// Mobile-first UI end-to-end test (real backend + isolated Docker DB; Discord posting captured).
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

// Editor and board links for two classes, as the bot would hand them out (tests/e2e/server.py).
const LINKS = await (await fetch('http://127.0.0.1:8011/e2e/links')).json()

async function openEditor(page, link = LINKS.mine.editor) {
  await page.goto(link)
}

let currentPage = null // screenshotted when a step fails

async function step(name, fn) {
  try {
    await fn()
    results.push(['PASS', name])
    console.log(`PASS  ${name}`)
  } catch (error) {
    results.push(['FAIL', name, error.message])
    if (currentPage) await currentPage.screenshot({ path: `${SHOTS}/FAIL-${results.length}.png`, fullPage: true }).catch(() => {})
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
  currentPage = page
  const apiCalls = []
  page.on('request', (req) => {
    if (req.url().includes(':8011/api/')) apiCalls.push(`${req.method()} ${new URL(req.url()).pathname}`)
  })
  page.on('response', async (res) => {
    if (res.url().includes(':8011/api/') && res.status() >= 400 && process.env.E2E_VERBOSE) {
      console.log(`      ${res.status()} ${res.request().method()} ${new URL(res.url()).pathname} ${await res.text().catch(() => '')}`)
    }
  })

  await step('editor without a link explains how to get one', async () => {
    await page.goto(`${APP}/cr/`)
    await page.getByRole('heading', { name: 'Open the editor from Discord' }).waitFor({ timeout: 5000 })
    await page.getByText('/manage').first().waitFor()
  })

  await step('a forged link is refused', async () => {
    await page.goto(`${APP}/cr/#t=e1.1.1.9999999999.forged`)
    await page.getByRole('heading', { name: 'This link has expired' }).waitFor({ timeout: 5000 })
  })

  await step('CR opens the /manage link and lands on the class, token removed from the URL', async () => {
    await openEditor(page)
    await page.getByRole('heading', { name: 'Exams', level: 1 }).waitFor({ timeout: 5000 })
    await page.locator('.brand-name', { hasText: 'E2E Class A' }).waitFor()
    assert.ok(!page.url().includes('t='), `token still in URL: ${page.url()}`)
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
    const oddEven = await page.getByText(/odd|even/i).allTextContents()
    assert.deepEqual(oddEven, [], 'no odd/even explanation on the site')
    await page.screenshot({ path: `${SHOTS}/02-course-invalid-360.png`, fullPage: true })
  })

  await step('theory course: a teacher per course section, inline faculty add, save', async () => {
    await page.getByLabel(/Course code/).fill(`${prefix}-415`)
    await page.getByLabel(/Course title/).fill(`Interaction Design ${prefix}`)
    await page.getByLabel('Short names students use').fill(`IDX${prefix}`)
    for (const name of [`Ayesha ${prefix}`, `Rahim ${prefix}`, `Karim ${prefix}`]) {
      await page.getByPlaceholder('Add a faculty member').fill(name)
      await page.getByRole('button', { name: 'Add', exact: true }).click()
      await page.locator('#section-A-teacher option', { hasText: name }).waitFor({ state: 'attached' })
    }
    // New teachers fill the empty sections in order.
    const selected = (id) => page.locator(`#${id} option:checked`).textContent()
    assert.equal(await selected('section-A-teacher'), `Ayesha ${prefix}`)
    assert.equal(await selected('section-B-teacher'), `Rahim ${prefix}`)
    await page.getByLabel('Section B').selectOption('')
    await page.getByRole('button', { name: 'Add course' }).click()
    await page.getByText('Choose the course teacher for Section B.').waitFor()
    // One teacher may take both sections.
    await page.getByLabel('Section B').selectOption({ label: `Ayesha ${prefix}` })
    await page.getByRole('button', { name: 'Add course' }).click()
    await page.getByText(`Added ${prefix}-415.`).waitFor()
    await page.locator('.course-card', { hasText: `${prefix}-415` }).getByText(`Section B: Ayesha ${prefix}`).waitFor()
    // Then give Section B its own teacher.
    await page.locator('.course-card', { hasText: `${prefix}-415` }).getByRole('button', { name: 'Edit' }).click()
    await page.getByLabel('Section B').selectOption({ label: `Rahim ${prefix}` })
    await page.getByRole('button', { name: 'Save course' }).click()
    await page.getByText(`Saved ${prefix}-415.`).waitFor()
    await page.locator('.course-card', { hasText: `${prefix}-415` }).getByText(`Section B: Rahim ${prefix}`).waitFor()
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
    await page.getByLabel('Section A').selectOption({ label: `Ayesha ${prefix}` })
    await page.getByLabel('Section B').selectOption({ label: `Rahim ${prefix}` })
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
    assert.equal(await page.getByRole('group', { name: /Class section/ }).count(), 0, 'Theoretical exams have no class section')
    assert.equal(await page.getByRole('group', { name: /Faculty for this exam/ }).count(), 0, 'teachers come from the section')
    await page.getByRole('radio', { name: /^Course section B/ }).check()
    await page.locator('.readonly-field', { hasText: 'Faculty' }).getByText(`Rahim ${prefix}`).waitFor()
    await page.getByRole('radio', { name: /^Both course sections/ }).check()
    await page.locator('.readonly-field', { hasText: 'Faculty' }).getByText(`Course section A: Ayesha ${prefix}`).waitFor()

    await page.getByRole('radio', { name: 'CT 2' }).check()
    await page.getByRole('radio', { name: new RegExp(`${prefix}-416`) }).check()
    assert.deepEqual(await examTypeValues(page), ['Project Update', 'Evaluation', 'Online Exam', 'Project Presentation', 'Lab Test'])
    await page.getByRole('checkbox', { name: 'Both sections simultaneously' }).waitFor()
    assert.equal(await page.getByRole('radio', { name: 'CT 2' }).count(), 0)
    assert.equal(await page.getByRole('group', { name: /Faculty for this exam/ }).getByRole('checkbox').count(), 3)
    assert.equal(await page.getByRole('radio', { name: /^Both course sections/ }).count(), 0, 'no course sections for Sessional')
    await page.locator('.readonly-value').getByText(`Interaction Design Lab ${prefix}`).waitFor()
    await page.screenshot({ path: `${SHOTS}/04-exam-form-360.png`, fullPage: true })
  })

  await step('validation errors keep the entered values', async () => {
    await page.getByRole('radio', { name: 'Lab Test' }).check()
    await page.getByLabel('Syllabus').fill('Experiment 1\nExperiment 2')
    await page.getByRole('button', { name: 'Save exam' }).click()
    await page.getByText('Pick the exam date.').waitFor()
    await page.getByText('Choose the class section.').waitFor()
    assert.equal(await page.getByLabel('Syllabus').inputValue(), 'Experiment 1\nExperiment 2')
    await page.getByRole('checkbox', { name: 'Section A' }).check()
    await page.getByRole('checkbox', { name: 'Section B' }).check()
    assert.equal(await page.getByRole('checkbox', { name: 'Section A' }).isChecked(), false, 'one class section at a time')
  })

  await step('server/network failure keeps the form and says so', async () => {
    await page.getByLabel(/^Date/).selectOption(soon)
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
      const token = sessionStorage.getItem('aicr-editor-token')
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
    await page.getByLabel(/^Time/).selectOption('14')
    await page.getByLabel('Minutes').selectOption('30')
    await page.getByRole('button', { name: 'Save changes' }).click()
    await page.getByText(`Updated ${prefix}-416 Lab Test.`).waitFor()
    await page.locator('.exam-card', { hasText: `${prefix}-416` }).getByText(/2:30/).waitFor()
  })

  await step('post next week and a single exam to Discord, after confirming', async () => {
    const before = (await (await fetch('http://127.0.0.1:8011/e2e/posts')).json()).length
    assert.equal(await page.getByRole('button', { name: /This week|Next week/ }).count(), 0, 'week updates are posted from Discord')
    await page.getByRole('button', { name: '📣 Next exam notes' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: '📣 Next exam day' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Post' }).click()
    await page.getByText('Posted to Discord').waitFor()
    await page.locator('.exam-card', { hasText: `${prefix}-416` }).getByRole('button', { name: '📣 Post' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Post' }).click()
    await page.getByText(`Posted ${prefix}-416 Lab Test to Discord.`).waitFor()
    const posts = (await (await fetch('http://127.0.0.1:8011/e2e/posts')).json()).slice(before)
    assert.equal(posts.length, 2, 'cancel posts nothing')
    assert.ok(posts.every((p) => p.channel === LINKS.mine.channel))
    assert.match(posts[1].messages[0], new RegExp(`${prefix}-416`))
    assert.match(posts[1].messages[0], /Experiment 1/)
    await page.screenshot({ path: `${SHOTS}/05b-posted-360.png`, fullPage: true })
  })

  await step('student board shows the exam read-only, without signing in', async () => {
    const studentContext = await browser.newContext({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true })
    const student = await studentContext.newPage()
    const requests = []
    student.on('request', (request) => requests.push(new URL(request.url()).pathname))
    await student.goto(LINKS.mine.board)
    await student.getByRole('heading', { name: 'Upcoming exams', level: 1 }).waitFor({ timeout: 5000 })
    await student.locator('.brand-name', { hasText: 'E2E Class A' }).waitFor()
    const card = student.locator('.exam-card', { hasText: `${prefix}-416` })
    await card.waitFor()
    await card.getByText('Experiment 1').waitFor()
    await card.getByText(/2:30/).waitFor()
    assert.equal(await student.getByRole('button', { name: /Edit|Delete|New exam|Sign out/ }).count(), 0)
    assert.equal(await student.locator('input, textarea').count(), 0)
    assert.equal(await student.getByLabel('Email').count(), 0)
    assert.equal(await student.getByText(/Messenger/).count(), 0)

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

  await step('theory exam: the section picks its teacher; both sections share one sitting', async () => {
    const course415 = new RegExp(`${prefix}-415`)
    await page.getByRole('button', { name: '+ New exam' }).click()
    await page.getByRole('radio', { name: course415 }).check()
    await page.getByRole('radio', { name: 'CT 1' }).check()
    await page.getByRole('radio', { name: /^Course section A/ }).check()
    await page.getByLabel(/^Date/).selectOption(soon)
    await page.getByLabel(/^Time/).selectOption('09')
    await page.getByLabel('Syllabus').fill('Chapter 1')
    await page.getByRole('button', { name: 'Save exam' }).click()
    await page.getByText(`Saved ${prefix}-415 CT 1.`).waitFor()

    await page.getByRole('button', { name: '+ New exam' }).click()
    await page.getByRole('radio', { name: course415 }).check()
    await page.getByRole('radio', { name: 'CT 1' }).check()
    await page.getByRole('radio', { name: /^Course section B/ }).check()
    await page.getByText("Section A's CT 1 is on").waitFor()
    assert.equal(await page.getByLabel(/^Date/).inputValue(), soon, 'date starts from the other section')
    assert.equal(await page.getByLabel(/^Time/).inputValue(), '09')
    await page.getByLabel(/^Time/).selectOption('10')
    await page.getByText('saving will move it').waitFor()
    await page.getByLabel('Syllabus').fill('Chapter 4')
    await page.screenshot({ path: `${SHOTS}/08-theory-exam-form-360.png`, fullPage: true })
    await page.getByRole('button', { name: 'Save exam' }).click()
    await page.getByText(`Saved ${prefix}-415 CT 1.`).waitFor()

    const cards = page.locator('.exam-card', { hasText: `${prefix}-415` })
    await cards.nth(1).waitFor()
    assert.equal(await cards.count(), 2)
    for (const [section, teacher] of [['A', 'Ayesha'], ['B', 'Rahim']]) {
      const card = cards.filter({ hasText: `Section ${section}` })
      await card.getByText(/10:00/).waitFor()   // Section A moved with Section B
      await card.getByText(`${teacher} ${prefix}`).waitFor()
    }
    for (let i = 0; i < 2; i += 1) {
      await cards.first().getByRole('button', { name: 'Delete' }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()
      await page.getByRole('dialog').waitFor({ state: 'hidden' })
    }
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

// ---------------------------------------------------------------- one class never sees another
await step("another class's editor and board don't show this class's data", async () => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  const page = await context.newPage()
  await openEditor(page, LINKS.other.editor)
  await page.locator('.brand-name', { hasText: 'E2E Class B' }).waitFor({ timeout: 5000 })
  await nav(page, 'Courses').click()
  await page.getByRole('heading', { name: 'Courses', level: 1 }).waitFor()
  assert.equal(await page.getByText(`${prefix}-415`).count(), 0)
  await page.goto(LINKS.other.board)
  await page.getByRole('heading', { name: 'Upcoming exams', level: 1 }).waitFor({ timeout: 5000 })
  assert.equal(await page.locator('.exam-card', { hasText: prefix }).count(), 0)
  await page.goto(`${APP}/c/00000000-0000-4000-8000-000000000000`)
  await page.getByText('This class link is not valid').waitFor({ timeout: 5000 })
  await context.close()
})

// ---------------------------------------------------------------- layout at every viewport
for (const vp of VIEWPORTS) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.isMobile, hasTouch: vp.isMobile })
  const page = await context.newPage()
  await openEditor(page)
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
    await page.goto(LINKS.mine.board)
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
