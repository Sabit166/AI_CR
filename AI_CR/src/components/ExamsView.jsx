import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import DiscordPanel from './DiscordPanel.jsx'
import ExamForm from './ExamForm.jsx'
import { facultyText, formatDay, formatTime, groupByDay, sectionText } from '../lib/format.js'
import { Banner, ConfirmDialog, EmptyState, LoadingBlock, Spinner } from './ui.jsx'

const PAGE_SIZE = 20

export default function ExamsView({ data, notify, reloadCatalog, goToCourses, setClassInfo }) {
  const [scope, setScope] = useState('upcoming')
  const [list, setList] = useState({ exams: [], hasMore: false, today: null })
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null) // null | 'new' | exam
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [pendingPost, setPendingPost] = useState(null)
  const [posting, setPosting] = useState(false)

  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let ignore = false // a slower, older response must not overwrite a newer one
    api(`/api/exams?scope=${scope}&limit=${PAGE_SIZE}&offset=0`).then(
      (result) => {
        if (ignore) return
        setError('')
        setList({ exams: result.exams, hasMore: result.has_more, today: result.today })
        setLoading(false)
      },
      (loadError) => {
        if (ignore) return
        setError(loadError.message)
        setLoading(false)
      },
    )
    return () => {
      ignore = true
    }
  }, [scope, reloadKey])

  function reload() {
    setLoading(true)
    setError('')
    setReloadKey((key) => key + 1)
  }

  async function loadMore() {
    setLoadingMore(true)
    try {
      const result = await api(`/api/exams?scope=${scope}&limit=${PAGE_SIZE}&offset=${list.exams.length}`)
      setList((current) => ({ ...current, exams: [...current.exams, ...result.exams], hasMore: result.has_more }))
    } catch (loadError) {
      notify(`Could not load more: ${loadError.message}`, 'error')
    } finally {
      setLoadingMore(false)
    }
  }

  function changeScope(value) {
    if (value === scope) return
    setLoading(true)
    setError('')
    setScope(value)
  }

  function handleSaved(saved, isNew) {
    setEditing(null)
    notify(isNew ? `Saved ${saved.course_code} ${saved.exam_type}.` : `Updated ${saved.course_code} ${saved.exam_type}.`)
    reload()
    reloadCatalog() // per-course exam counts drive the "remove course" warning
  }

  async function confirmDelete() {
    setDeleting(true)
    try {
      await api(`/api/exams/${pendingDelete.id}`, { method: 'DELETE' })
      notify(`Deleted ${pendingDelete.course_code} ${pendingDelete.exam_type}.`)
      setList((current) => ({ ...current, exams: current.exams.filter((e) => e.id !== pendingDelete.id) }))
      setPendingDelete(null)
      reloadCatalog()
    } catch (deleteError) {
      notify(`Could not delete: ${deleteError.message}`, 'error')
    } finally {
      setDeleting(false)
    }
  }

  async function confirmPost() {
    setPosting(true)
    try {
      await api(`/api/discord/post/exams/${pendingPost.id}`, { method: 'POST' })
      notify(`Posted ${pendingPost.course_code} ${pendingPost.exam_type} to Discord.`)
      setPendingPost(null)
    } catch (postError) {
      notify(`Not posted: ${postError.message}`, 'error')
    } finally {
      setPosting(false)
    }
  }

  if (editing) {
    return (
      <ExamForm
        courses={data.courses}
        config={data.config}
        exam={editing === 'new' ? null : editing}
        onSaved={handleSaved}
        onCancel={() => setEditing(null)}
      />
    )
  }

  const noCourses = data.courses.length === 0

  return (
    <section aria-labelledby="exams-title">
      <div className="section-head">
        <h1 id="exams-title" className="section-title">
          Exams
        </h1>
        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')} disabled={noCourses}>
          + New exam
        </button>
      </div>

      <DiscordPanel classInfo={data.config.class} notify={notify} setClassInfo={setClassInfo} />

      {noCourses ? (
        <EmptyState
          title="Add your courses first"
          action={
            <button type="button" className="btn btn-primary" onClick={goToCourses}>
              Set up courses
            </button>
          }
        >
          Exam entries are built from the term's course list, so the bot always knows the right title, teachers and exam
          types.
        </EmptyState>
      ) : null}

      <div className="segmented" role="tablist" aria-label="Which exams">
        {[
          ['upcoming', 'Upcoming'],
          ['past', 'Past'],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={scope === value}
            className={`segment${scope === value ? ' segment-active' : ''}`}
            onClick={() => changeScope(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? <Banner onRetry={reload}>{error}</Banner> : null}
      {loading ? <LoadingBlock label="Loading exams…" /> : null}

      {!loading && !error && list.exams.length === 0 ? (
        <EmptyState title={scope === 'upcoming' ? 'No upcoming exams posted' : 'No past exams'}>
          {scope === 'upcoming' ? 'Exams you add here are what the Discord bot tells your class.' : null}
        </EmptyState>
      ) : null}

      {!loading
        ? groupByDay(list.exams).map((group) => (
            <div key={group.day} className="day-group">
              <h2 className="day-title">
                {formatDay(group.day)}
                {group.day === list.today ? <span className="badge badge-today">Today</span> : null}
              </h2>
              <ul className="card-list">
                {group.items.map((exam) => (
                  <li key={exam.id} className="card exam-card">
                    <div className="exam-card-main">
                      <p className="exam-card-course">
                        <strong>{exam.course_code}</strong> · {exam.course_title}
                      </p>
                      <p className="exam-card-meta">
                        <span className="badge badge-type">{exam.exam_type}</span>
                        {formatTime(exam.exam_time) ? <span>{formatTime(exam.exam_time)}</span> : <span className="muted">Time TBA</span>}
                        <span>{sectionText(exam)}</span>
                      </p>
                      {exam.syllabus ? <p className="exam-card-syllabus">{exam.syllabus}</p> : <p className="muted small">No syllabus yet</p>}
                      {facultyText(exam) ? <p className="muted small">👤 {facultyText(exam)}</p> : null}
                    </div>
                    <div className="card-actions">
                      {scope === 'upcoming' && data.config.class.linked ? (
                        <button type="button" className="btn btn-ghost btn-small" onClick={() => setPendingPost(exam)}>
                          📣 Post
                        </button>
                      ) : null}
                      <button type="button" className="btn btn-ghost btn-small" onClick={() => setEditing(exam)}>
                        Edit
                      </button>
                      <button type="button" className="btn btn-danger-ghost btn-small" onClick={() => setPendingDelete(exam)}>
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))
        : null}

      {list.hasMore && !loading ? (
        <button
          type="button"
          className="btn btn-ghost btn-block"
          onClick={loadMore}
          disabled={loadingMore}
        >
          {loadingMore ? <Spinner label="Loading more…" /> : null}
          Load more
        </button>
      ) : null}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this exam?"
        busy={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      >
        {pendingDelete ? (
          <p>
            {pendingDelete.course_code} {pendingDelete.exam_type} on {formatDay(pendingDelete.exam_date)} will be removed and
            students will no longer see it.
          </p>
        ) : null}
      </ConfirmDialog>

      <ConfirmDialog
        open={Boolean(pendingPost)}
        title="Post this exam to Discord?"
        confirmLabel="Post"
        tone="primary"
        busy={posting}
        onConfirm={confirmPost}
        onCancel={() => setPendingPost(null)}
      >
        {pendingPost ? (
          <p>
            {pendingPost.course_code} {pendingPost.exam_type} on {formatDay(pendingPost.exam_date)}, with its time, syllabus and
            notes, will be posted in the class channel for everyone.
          </p>
        ) : null}
      </ConfirmDialog>
    </section>
  )
}
