import { useState } from 'react'
import { api, ApiError } from '../lib/api.js'
import { facultyCountHint, parseCourseCode } from '../lib/academic.js'
import { Banner, CheckList, Field, Spinner, TypeBadge } from './ui.jsx'

export default function CourseForm({ course, faculty, rules, onSaved, onCancel, onFacultyAdded }) {
  const editing = Boolean(course)
  const [form, setForm] = useState(() => ({
    code: course?.code ?? '',
    title: course?.title ?? '',
    aliases: (course?.aliases ?? []).join(', '),
    faculty_ids: (course?.faculty ?? []).map((f) => f.id),
  }))
  const [touched, setTouched] = useState({})
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [newFaculty, setNewFaculty] = useState('')
  const [addingFaculty, setAddingFaculty] = useState(false)

  const parsed = parseCourseCode(form.code)
  const count = form.faculty_ids.length
  const countHint = parsed.courseType ? facultyCountHint(parsed.courseType, count, rules) : null
  const typeWillChange = editing && course.exam_count > 0 && parsed.courseType && parsed.courseType !== course.course_type

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  function toggleFaculty(id) {
    update('faculty_ids', form.faculty_ids.includes(id) ? form.faculty_ids.filter((f) => f !== id) : [...form.faculty_ids, id])
  }

  async function addFaculty() {
    const name = newFaculty.trim().replace(/\s+/g, ' ')
    if (name.length < 2 || addingFaculty) return
    setAddingFaculty(true)
    try {
      const created = await api('/api/faculty', { method: 'POST', body: { name } })
      onFacultyAdded(created)
      update('faculty_ids', [...form.faculty_ids, created.id])
      setNewFaculty('')
    } catch (error) {
      setErrors((current) => ({ ...current, new_faculty: error.message }))
    } finally {
      setAddingFaculty(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    if (saving) return
    setTouched({ code: true, title: true })
    setFormError('')
    const next = {}
    if (parsed.error) next.code = parsed.error
    if (form.title.trim().length < 2) next.title = 'Course title is required.'
    if (countHint && !countHint.ok) next.faculty_ids = `${countHint.text} You selected ${count}.`
    setErrors(next)
    if (Object.keys(next).length) return

    setSaving(true)
    try {
      const saved = await api(editing ? `/api/courses/${course.id}` : '/api/courses', {
        method: editing ? 'PATCH' : 'POST',
        body: {
          code: form.code,
          title: form.title,
          aliases: form.aliases.split(',').map((a) => a.trim()).filter(Boolean),
          faculty_ids: form.faculty_ids,
        },
      })
      onSaved(saved, !editing)
    } catch (error) {
      if (error instanceof ApiError && error.field && error.field in form) {
        setErrors({ [error.field]: error.message })
        setFormError('Please fix the highlighted field.')
      } else {
        setFormError(`${error.message} Your entries are kept — try again.`)
      }
    } finally {
      setSaving(false)
    }
  }

  const codeError = errors.code ?? (touched.code && form.code ? parsed.error : null)

  return (
    <form className="card form-card" onSubmit={submit} noValidate aria-labelledby="course-form-title">
      <div className="form-head">
        <h2 id="course-form-title">{editing ? `Edit ${course.code}` : 'Add course'}</h2>
        <button type="button" className="btn btn-ghost btn-small" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>

      <Field label="Course code" htmlFor="course-code" error={codeError} required>
        <input
          id="course-code"
          type="text"
          autoCapitalize="characters"
          autoComplete="off"
          placeholder="e.g. CSE-415"
          maxLength={20}
          value={form.code}
          onChange={(e) => update('code', e.target.value)}
          onBlur={() => setTouched((t) => ({ ...t, code: true }))}
          aria-invalid={Boolean(codeError)}
          aria-describedby="course-type-derived"
        />
      </Field>
      <p id="course-type-derived" className="derived" aria-live="polite">
        {parsed.courseType ? (
          <>
            <TypeBadge type={parsed.courseType} /> {parsed.code}
          </>
        ) : (
          <span className="muted">The course type is filled in from the code.</span>
        )}
      </p>
      {typeWillChange ? (
        <Banner>
          This code would make it a {parsed.courseType} course, but it already has exam records. Keep the original
          code, or add a new course instead.
        </Banner>
      ) : null}

      <Field label="Course title" htmlFor="course-title" error={errors.title} required>
        <input
          id="course-title"
          type="text"
          maxLength={200}
          value={form.title}
          onChange={(e) => update('title', e.target.value)}
          aria-invalid={Boolean(errors.title)}
        />
      </Field>

      <Field
        label="Short names students use"
        htmlFor="course-aliases"
        hint="Optional, comma separated — e.g. HCI, Interface. Common initials are recognised automatically."
        error={errors.aliases}
      >
        <input id="course-aliases" type="text" value={form.aliases} onChange={(e) => update('aliases', e.target.value)} />
      </Field>

      <CheckList
        legend={`Course teachers (${count} selected)`}
        options={faculty.map((f) => ({ value: f.id, label: f.name }))}
        selected={form.faculty_ids}
        onToggle={toggleFaculty}
        emptyText="No faculty yet — add the first one below."
        hint={countHint?.text}
        error={errors.faculty_ids}
      />

      <div className="inline-add">
        <label htmlFor="new-faculty" className="visually-hidden">
          New faculty name
        </label>
        <input
          id="new-faculty"
          type="text"
          placeholder="Add a faculty member"
          value={newFaculty}
          onChange={(e) => {
            setNewFaculty(e.target.value)
            setErrors((current) => ({ ...current, new_faculty: undefined }))
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addFaculty()
            }
          }}
        />
        <button type="button" className="btn btn-ghost" onClick={addFaculty} disabled={addingFaculty || newFaculty.trim().length < 2}>
          {addingFaculty ? <Spinner label="Adding…" /> : null}
          Add
        </button>
      </div>
      {errors.new_faculty ? (
        <p className="field-error" role="alert">
          {errors.new_faculty}
        </p>
      ) : null}

      {formError ? <Banner>{formError}</Banner> : null}

      <div className="form-actions sticky-actions">
        <button type="submit" className="btn btn-primary btn-block" disabled={saving || typeWillChange}>
          {saving ? <Spinner label="Saving…" /> : null}
          {saving ? 'Saving…' : editing ? 'Save course' : 'Add course'}
        </button>
      </div>
    </form>
  )
}
