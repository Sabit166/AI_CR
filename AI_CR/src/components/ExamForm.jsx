import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api.js'
import { COURSE_SECTIONS, hasCourseSections, hasSections } from '../lib/academic.js'
import { formatDay, formatTime, sectionText } from '../lib/format.js'
import { dateOptions, hourOptions, joinTime, minuteOptions, splitTime } from '../lib/pickers.js'
import { Banner, CheckList, ChipGroup, Field, Spinner, TypeBadge } from './ui.jsx'

const DRAFT_KEY = 'aicr:exam-draft'
const BOTH = 'both' // Theoretical exam for both course sections (stored as course_section NULL)

const BLANK = {
  course_id: null,
  exam_type: '',
  exam_date: '',
  exam_time: '',
  section: '',
  course_section: '',
  syllabus: '',
  venue: '',
  remarks: '',
  notes_link: '',
  faculty_ids: [],
}

function fromExam(exam) {
  return {
    course_id: exam.course_id,
    exam_type: exam.exam_type,
    exam_date: exam.exam_date,
    exam_time: exam.exam_time ? exam.exam_time.slice(0, 5) : '',
    section: exam.section ?? '',
    course_section: hasCourseSections(exam.course_type) ? (exam.course_section ?? BOTH) : '',
    syllabus: exam.syllabus ?? '',
    venue: exam.venue ?? '',
    remarks: exam.remarks ?? '',
    notes_link: exam.notes_link ?? '',
    faculty_ids: exam.exam_faculty_ids ?? [],
  }
}

function loadDraft() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? 'null')
    return saved && typeof saved === 'object' ? { ...BLANK, ...saved } : null
  } catch {
    return null
  }
}

function newRequestId() {
  return crypto.randomUUID()
}

/** Teachers of the chosen course section(s): [{ section: 'A', name }]. */
function sectionTeachers(course, courseSection) {
  return COURSE_SECTIONS.filter((s) => courseSection === BOTH || courseSection === s).map((s) => ({
    section: s,
    name: course?.section_faculty?.[s]?.name ?? null,
  }))
}

export default function ExamForm({ courses, config, exam, onSaved, onCancel }) {
  const editing = Boolean(exam)
  const [restoredDraft] = useState(() => (editing ? null : loadDraft()))
  const [form, setForm] = useState(() => (editing ? fromExam(exam) : restoredDraft ?? BLANK))
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [requestId, setRequestId] = useState(newRequestId)
  const [preview, setPreview] = useState({ loading: false, text: '', error: '' })
  const [siblingState, setSiblingState] = useState({ key: null, exams: [] })

  // Editing an exam whose course was later removed: keep it selectable for this record only.
  const courseOptions = useMemo(() => {
    if (!exam || courses.some((c) => c.id === exam.course_id)) return courses
    return [
      ...courses,
      {
        id: exam.course_id,
        code: exam.course_code,
        title: exam.course_title,
        course_type: exam.course_type,
        faculty: [],
        section_faculty: {},
        archived: true,
      },
    ]
  }, [courses, exam])

  const course = courseOptions.find((c) => c.id === form.course_id) ?? null
  const sectioned = course ? hasSections(course.course_type) : false
  const theory = course ? hasCourseSections(course.course_type) : false

  const examTypes = useMemo(() => {
    if (!course) return []
    const allowed = [...(config.exam_types[course.course_type] ?? [])]
    // A legacy record can be edited without being forced to change type.
    if (exam && exam.course_id === course.id && !allowed.includes(exam.exam_type)) allowed.push(exam.exam_type)
    return allowed
  }, [course, config, exam])

  const dates = useMemo(() => dateOptions(config.today, { include: form.exam_date }), [config.today, form.exam_date])
  const time = splitTime(form.exam_time)
  const hours = useMemo(() => hourOptions(form.exam_time), [form.exam_time])
  const minutes = useMemo(() => minuteOptions(form.exam_time), [form.exam_time])

  useEffect(() => {
    if (!editing) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(form))
  }, [form, editing])

  // Both course sections sit a Theoretical exam together: find the other section's record of this exam.
  const siblingKey = theory && form.course_id && form.exam_type ? `${form.course_id}|${form.exam_type}` : null
  const siblings = siblingState.key === siblingKey ? siblingState.exams : []
  useEffect(() => {
    if (!siblingKey) return undefined
    let cancelled = false
    api(`/api/exams?scope=upcoming&course_id=${form.course_id}&limit=100`)
      .then(({ exams }) => {
        if (cancelled) return
        const found = exams.filter((e) => e.exam_type === form.exam_type && e.id !== exam?.id)
        setSiblingState({ key: siblingKey, exams: found })
        // New exam with no date yet: start from the other section's date and time.
        if (!editing && found.length) {
          setForm((current) =>
            current.exam_date
              ? current
              : { ...current, exam_date: found[0].exam_date, exam_time: found[0].exam_time?.slice(0, 5) ?? '' },
          )
        }
      })
      .catch(() => !cancelled && setSiblingState({ key: siblingKey, exams: [] }))
    return () => {
      cancelled = true
    }
  }, [siblingKey, form.course_id, form.exam_type, editing, exam?.id])

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    setPreview((current) => (current.text ? { ...current, text: '' } : current))
  }

  function selectCourse(courseId) {
    const next = courseOptions.find((c) => c.id === courseId)
    const allowed = config.exam_types[next.course_type] ?? []
    const facultyIds = new Set(next.faculty.map((f) => f.id))
    setForm((current) => ({
      ...current,
      course_id: courseId,
      // Never carry over an exam type or teachers that belong to a different course.
      exam_type: allowed.includes(current.exam_type) ? current.exam_type : '',
      faculty_ids: current.faculty_ids.filter((id) => facultyIds.has(id)),
      section: hasSections(next.course_type) ? current.section : '',
      course_section: hasCourseSections(next.course_type) ? current.course_section : '',
    }))
    setErrors({})
  }

  function toggleFaculty(id) {
    update('faculty_ids', form.faculty_ids.includes(id) ? form.faculty_ids.filter((f) => f !== id) : [...form.faculty_ids, id])
  }

  function payload() {
    return {
      course_id: form.course_id,
      exam_type: form.exam_type,
      exam_date: form.exam_date,
      exam_time: form.exam_time || null,
      section: sectioned ? form.section.trim() || null : null,
      course_section: theory && form.course_section !== BOTH ? form.course_section : null,
      syllabus: form.syllabus,
      venue: form.venue,
      remarks: form.remarks,
      notes_link: form.notes_link.trim(),
      faculty_ids: theory ? [] : form.faculty_ids,
      ...(editing ? {} : { client_request_id: requestId }),
    }
  }

  function validate() {
    const next = {}
    if (!form.course_id) next.course_id = 'Select a course.'
    if (form.course_id && !form.exam_type) next.exam_type = 'Select the exam type.'
    if (theory && !form.course_section) next.course_section = 'Choose the section.'
    if (theory && form.course_section) {
      const missing = sectionTeachers(course, form.course_section).filter((t) => !t.name)
      if (missing.length) {
        next.course_section = `Section ${missing.map((t) => t.section).join(' and ')} has no course teacher yet. Assign it under Courses first.`
      }
    }
    if (!form.exam_date) next.exam_date = 'Pick the exam date.'
    if (form.notes_link.trim() && !/^https?:\/\/\S+$/i.test(form.notes_link.trim())) {
      next.notes_link = 'Use a full link starting with https://'
    }
    if (sectioned && form.section.trim() && !/^[A-Za-z0-9]{1,10}$/.test(form.section.trim())) {
      next.section = 'Use letters or numbers only, e.g. A. Leave empty for the whole class.'
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function submit(event) {
    event.preventDefault()
    if (saving) return // double-tap guard (the request id also makes retries idempotent)
    setFormError('')
    if (!validate()) return
    setSaving(true)
    try {
      const saved = await api(editing ? `/api/exams/${exam.id}` : '/api/exams', {
        method: editing ? 'PATCH' : 'POST',
        body: payload(),
      })
      if (!editing) {
        sessionStorage.removeItem(DRAFT_KEY)
        setRequestId(newRequestId())
      }
      onSaved(saved, !editing)
    } catch (error) {
      // Keep everything the CR typed; show the problem next to the field when we know it.
      if (error instanceof ApiError && error.field && error.field in BLANK) {
        setErrors({ [error.field]: error.message })
        setFormError('Please fix the highlighted field.')
      } else {
        setFormError(`${error.message} Your entries are kept — try again.`)
      }
    } finally {
      setSaving(false)
    }
  }

  async function showPreview() {
    if (!validate()) return
    setPreview({ loading: true, text: '', error: '' })
    try {
      const result = await api('/api/exams/preview', { method: 'POST', body: payload() })
      setPreview({ loading: false, text: result.text, error: '' })
    } catch (error) {
      setPreview({ loading: false, text: '', error: error.message })
    }
  }

  function cancel() {
    if (!editing) sessionStorage.removeItem(DRAFT_KEY)
    onCancel()
  }

  const courseChoices = courseOptions.map((c) => ({
    value: c.id,
    label: c.code,
    sub: c.archived ? 'removed course' : c.course_type,
  }))

  const sectionChoices = course
    ? [
        ...COURSE_SECTIONS.map((s) => ({
          value: s,
          label: `Section ${s}`,
          sub: course.section_faculty?.[s]?.name ?? 'no teacher yet',
        })),
        { value: BOTH, label: 'Both sections', sub: 'one record for A & B' },
      ]
    : []
  const chosenTeachers = theory && form.course_section ? sectionTeachers(course, form.course_section) : []
  const movedSiblings = siblings.filter(
    (s) => s.exam_date !== form.exam_date || (s.exam_time?.slice(0, 5) ?? '') !== form.exam_time,
  )

  return (
    <form className="card form-card" onSubmit={submit} noValidate aria-labelledby="exam-form-title">
      <div className="form-head">
        <h2 id="exam-form-title">{editing ? 'Edit exam' : 'New exam'}</h2>
        <button type="button" className="btn btn-ghost btn-small" onClick={cancel} disabled={saving}>
          Cancel
        </button>
      </div>

      {restoredDraft && !editing ? <Banner kind="info">Restored your unsaved entry.</Banner> : null}

      <ChipGroup
        legend="Course"
        name="exam-course"
        options={courseChoices}
        value={form.course_id}
        onChange={selectCourse}
        error={errors.course_id}
        required
      />

      <div className="readonly-field" aria-live="polite">
        <span className="field-label">Course title</span>
        {course ? (
          <p className="readonly-value">
            {course.title} <TypeBadge type={course.course_type} />
          </p>
        ) : (
          <p className="muted">Filled in automatically after you pick a course.</p>
        )}
      </div>

      {course ? (
        <ChipGroup
          legend="Exam type"
          name="exam-type"
          options={examTypes.map((t) => ({ value: t, label: t }))}
          value={form.exam_type}
          onChange={(value) => update('exam_type', value)}
          error={errors.exam_type}
          required
        />
      ) : null}

      {theory ? (
        <>
          <ChipGroup
            legend="Section"
            name="exam-course-section"
            options={sectionChoices}
            value={form.course_section}
            onChange={(value) => update('course_section', value)}
            error={errors.course_section}
            required
          />
          <div className="readonly-field" aria-live="polite">
            <span className="field-label">Faculty</span>
            {chosenTeachers.length ? (
              chosenTeachers.map((t) => (
                <p key={t.section} className="readonly-value">
                  👤 {chosenTeachers.length > 1 ? `Section ${t.section}: ` : ''}
                  {t.name ?? <span className="muted">not assigned</span>}
                </p>
              ))
            ) : (
              <p className="muted">Filled in automatically from the section's course teacher.</p>
            )}
          </div>
        </>
      ) : null}

      {theory && siblings.length ? (
        <Banner kind="info">
          {siblings.map((s) => (
            <span key={s.id} className="sibling-line">
              {sectionText(s)}'s {s.exam_type} is on {formatDay(s.exam_date)}
              {s.exam_time ? ` · ${formatTime(s.exam_time)}` : ''}.
            </span>
          ))}{' '}
          Both sections sit it together
          {movedSiblings.length ? ', so saving will move it to the date and time below.' : '.'}
        </Banner>
      ) : null}

      <div className="field-row">
        <Field label="Date" htmlFor="exam-date" error={errors.exam_date} required>
          <select
            id="exam-date"
            value={form.exam_date}
            onChange={(e) => update('exam_date', e.target.value)}
            aria-invalid={Boolean(errors.exam_date)}
            required
          >
            <option value="">Choose a date…</option>
            {dates.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </Field>
        <Field label="Time" htmlFor="exam-time" hint="Optional" error={errors.exam_time}>
          <div className="time-selects">
            <select
              id="exam-time"
              value={time.hour}
              onChange={(e) => update('exam_time', joinTime(e.target.value, time.minute))}
            >
              <option value="">Not set</option>
              {hours.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              aria-label="Minutes"
              value={time.minute}
              disabled={!time.hour}
              onChange={(e) => update('exam_time', joinTime(time.hour, e.target.value))}
            >
              {time.hour ? null : <option value="">:00</option>}
              {minutes.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </Field>
      </div>

      {sectioned ? (
        <Field label="Section" htmlFor="exam-section" hint="Leave empty if it's for the whole class." error={errors.section}>
          <input
            id="exam-section"
            type="text"
            inputMode="text"
            autoCapitalize="characters"
            maxLength={10}
            placeholder="Whole class"
            value={form.section}
            onChange={(e) => update('section', e.target.value.toUpperCase())}
            aria-invalid={Boolean(errors.section)}
          />
        </Field>
      ) : null}

      {course && !theory ? (
        <CheckList
          legend="Faculty for this exam"
          options={course.faculty.map((f) => ({ value: f.id, label: f.name }))}
          selected={form.faculty_ids}
          onToggle={toggleFaculty}
          emptyText="No faculty assigned to this course yet. Add them under Courses."
          hint="Optional. If none are ticked, students see the course's faculty."
          error={errors.faculty_ids}
        />
      ) : null}

      <Field label="Syllabus" htmlFor="exam-syllabus" hint="Line breaks are kept." error={errors.syllabus}>
        <textarea
          id="exam-syllabus"
          rows={5}
          value={form.syllabus}
          onChange={(e) => update('syllabus', e.target.value)}
          placeholder={'e.g.\nChapter 2 (full)\nChapter 3 up to 3.4'}
        />
      </Field>

      <details className="more" open={Boolean(form.venue || form.notes_link || form.remarks)}>
        <summary>More details (venue, notes link, remarks)</summary>
        <Field label="Venue" htmlFor="exam-venue" error={errors.venue}>
          <input id="exam-venue" type="text" maxLength={200} value={form.venue} onChange={(e) => update('venue', e.target.value)} />
        </Field>
        <Field label="Notes link" htmlFor="exam-link" error={errors.notes_link}>
          <input
            id="exam-link"
            type="url"
            inputMode="url"
            placeholder="https://"
            value={form.notes_link}
            onChange={(e) => update('notes_link', e.target.value)}
            aria-invalid={Boolean(errors.notes_link)}
          />
        </Field>
        <Field label="Remarks" htmlFor="exam-remarks" error={errors.remarks}>
          <textarea id="exam-remarks" rows={2} maxLength={2000} value={form.remarks} onChange={(e) => update('remarks', e.target.value)} />
        </Field>
      </details>

      {preview.text ? (
        <div className="preview">
          <p className="field-label">What students will see</p>
          <pre>{preview.text}</pre>
        </div>
      ) : null}
      {preview.error ? <Banner>{preview.error}</Banner> : null}
      {formError ? <Banner>{formError}</Banner> : null}

      <div className="form-actions sticky-actions">
        <button type="button" className="btn btn-ghost" onClick={showPreview} disabled={saving || preview.loading}>
          {preview.loading ? <Spinner label="Loading preview…" /> : null}
          Preview
        </button>
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? <Spinner label="Saving…" /> : null}
          {saving ? 'Saving…' : editing ? 'Save changes' : 'Save exam'}
        </button>
      </div>
    </form>
  )
}
