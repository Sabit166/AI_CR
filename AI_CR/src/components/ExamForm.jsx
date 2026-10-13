import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api.js'
import { hasSections } from '../lib/academic.js'
import { Banner, CheckList, ChipGroup, Field, Spinner, TypeBadge } from './ui.jsx'

const DRAFT_KEY = 'aicr:exam-draft'

const BLANK = {
  course_id: null,
  exam_type: '',
  exam_date: '',
  exam_time: '',
  section: '',
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

export default function ExamForm({ courses, config, exam, onSaved, onCancel }) {
  const editing = Boolean(exam)
  const [restoredDraft] = useState(() => (editing ? null : loadDraft()))
  const [form, setForm] = useState(() => (editing ? fromExam(exam) : restoredDraft ?? BLANK))
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [requestId, setRequestId] = useState(newRequestId)
  const [preview, setPreview] = useState({ loading: false, text: '', error: '' })

  // Editing an exam whose course was later removed: keep it selectable for this record only.
  const courseOptions = useMemo(() => {
    if (!exam || courses.some((c) => c.id === exam.course_id)) return courses
    return [
      ...courses,
      { id: exam.course_id, code: exam.course_code, title: exam.course_title, course_type: exam.course_type, faculty: [], archived: true },
    ]
  }, [courses, exam])

  const course = courseOptions.find((c) => c.id === form.course_id) ?? null
  const sectioned = course ? hasSections(course.course_type) : false

  const examTypes = useMemo(() => {
    if (!course) return []
    const allowed = [...(config.exam_types[course.course_type] ?? [])]
    // A legacy record (e.g. "Mid") can be edited without being forced to change type.
    if (exam && exam.course_id === course.id && !allowed.includes(exam.exam_type)) allowed.push(exam.exam_type)
    return allowed
  }, [course, config, exam])

  useEffect(() => {
    if (!editing) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(form))
  }, [form, editing])

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
      syllabus: form.syllabus,
      venue: form.venue,
      remarks: form.remarks,
      notes_link: form.notes_link.trim(),
      faculty_ids: form.faculty_ids,
      ...(editing ? {} : { client_request_id: requestId }),
    }
  }

  function validate() {
    const next = {}
    if (!form.course_id) next.course_id = 'Select a course.'
    if (form.course_id && !form.exam_type) next.exam_type = 'Select the exam type.'
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

      <div className="field-row">
        <Field label="Date" htmlFor="exam-date" error={errors.exam_date} required>
          <input
            id="exam-date"
            type="date"
            value={form.exam_date}
            onChange={(e) => update('exam_date', e.target.value)}
            aria-invalid={Boolean(errors.exam_date)}
            required
          />
        </Field>
        <Field label="Time" htmlFor="exam-time" hint="Optional" error={errors.exam_time}>
          <input id="exam-time" type="time" value={form.exam_time} onChange={(e) => update('exam_time', e.target.value)} />
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

      {course ? (
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
