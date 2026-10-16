import { useState } from 'react'
import { api } from '../lib/api.js'
import { COURSE_SECTIONS, hasCourseSections, missingSections } from '../lib/academic.js'
import CourseForm from './CourseForm.jsx'
import { ConfirmDialog, EmptyState, TypeBadge } from './ui.jsx'

export default function CoursesView({ data, notify, reloadCatalog }) {
  const [editing, setEditing] = useState(null) // null | 'new' | course
  const [pendingRemove, setPendingRemove] = useState(null)
  const [removing, setRemoving] = useState(false)
  const [extraFaculty, setExtraFaculty] = useState([])

  const faculty = [...data.faculty, ...extraFaculty.filter((f) => !data.faculty.some((d) => d.id === f.id))].sort((a, b) =>
    a.name.localeCompare(b.name),
  )

  async function handleSaved(saved, isNew) {
    setEditing(null)
    setExtraFaculty([])
    notify(isNew ? `Added ${saved.code}.` : `Saved ${saved.code}.`)
    await reloadCatalog()
  }

  async function confirmRemove() {
    setRemoving(true)
    try {
      const { result } = await api(`/api/courses/${pendingRemove.id}`, { method: 'DELETE' })
      notify(
        result === 'archived'
          ? `${pendingRemove.code} removed from this term. Its past exam records are kept.`
          : `${pendingRemove.code} deleted.`,
      )
      setPendingRemove(null)
      await reloadCatalog()
    } catch (error) {
      notify(`Could not remove: ${error.message}`, 'error')
    } finally {
      setRemoving(false)
    }
  }

  if (editing) {
    return (
      <CourseForm
        course={editing === 'new' ? null : editing}
        faculty={faculty}
        onSaved={handleSaved}
        onCancel={() => {
          setEditing(null)
          if (extraFaculty.length) reloadCatalog()
          setExtraFaculty([])
        }}
        onFacultyAdded={(created) => setExtraFaculty((current) => [...current, created])}
      />
    )
  }

  return (
    <section aria-labelledby="courses-title">
      <div className="section-head">
        <h1 id="courses-title" className="section-title">
          Courses
        </h1>
        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
          + Add course
        </button>
      </div>
      <p className="muted section-lead">
        This term's courses for this class. The Discord bot and the exam form both read this list, so changes apply right away.
      </p>

      {data.courses.length === 0 ? (
        <EmptyState title="No courses yet">Add each course you take this term — as many as you need.</EmptyState>
      ) : (
        <ul className="card-list">
          {data.courses.map((course) => (
            <li key={course.id} className="card course-card">
              <div className="course-card-main">
                <p className="course-card-code">
                  <strong>{course.code}</strong> <TypeBadge type={course.course_type} />
                </p>
                <p className="course-card-title">{course.title}</p>
                {hasCourseSections(course.course_type) ? (
                  <>
                    {COURSE_SECTIONS.map((section) => (
                      <p key={section} className="muted small">
                        👤 Section {section}: {course.section_faculty?.[section]?.name ?? 'not assigned'}
                      </p>
                    ))}
                    {missingSections(course.section_faculty).length ? (
                      <p className="small field-error">Tap Edit to choose the section teachers.</p>
                    ) : null}
                  </>
                ) : (
                  <p className="muted small">
                    👤 {course.faculty.length ? course.faculty.map((f) => f.name).join(', ') : 'No faculty assigned'}
                  </p>
                )}
                {course.aliases.length ? <p className="muted small">Also called: {course.aliases.join(', ')}</p> : null}
                <p className="muted small">
                  {course.exam_count} exam record{course.exam_count === 1 ? '' : 's'}
                </p>
              </div>
              <div className="card-actions">
                <button type="button" className="btn btn-ghost btn-small" onClick={() => setEditing(course)}>
                  Edit
                </button>
                <button type="button" className="btn btn-danger-ghost btn-small" onClick={() => setPendingRemove(course)}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={Boolean(pendingRemove)}
        title={`Remove ${pendingRemove?.code ?? ''}?`}
        confirmLabel="Remove"
        busy={removing}
        onConfirm={confirmRemove}
        onCancel={() => setPendingRemove(null)}
      >
        {pendingRemove?.exam_count ? (
          <p>
            It has {pendingRemove.exam_count} exam record{pendingRemove.exam_count === 1 ? '' : 's'}. The course will be removed from
            this term's list, but those records are kept and stay linked to it.
          </p>
        ) : (
          <p>It has no exam records, so it will be deleted.</p>
        )}
      </ConfirmDialog>
    </section>
  )
}
