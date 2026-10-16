import { useEffect, useState } from 'react'
import { classKeyFromPath, publicApi } from '../lib/publicApi.js'
import {
  facultyText,
  formatDay,
  formatTime,
  groupByDay,
  groupByWeek,
  isSafeLink,
  relativeDayBadge,
  sectionText,
} from '../lib/format.js'
import { Banner, EmptyState, LoadingBlock, Spinner } from '../components/ui.jsx'

const PAGE_SIZE = 20

function ExamCard({ exam }) {
  const time = formatTime(exam.exam_time)
  return (
    <li className="card exam-card student-exam">
      <div className="exam-card-main">
        <p className="exam-card-course">
          <strong>{exam.course_code}</strong> · {exam.course_title}
        </p>
        <p className="exam-card-meta">
          <span className="badge badge-type">{exam.exam_type}</span>
          {time ? <span>🕘 {time}</span> : <span className="muted">Time TBA</span>}
          <span>{sectionText(exam)}</span>
          {exam.venue ? <span>📍 {exam.venue}</span> : null}
        </p>
        {exam.syllabus ? (
          <div className="student-syllabus">
            <p className="student-label">📖 Syllabus</p>
            <p className="student-syllabus-text">{exam.syllabus}</p>
          </div>
        ) : (
          <p className="muted small">Syllabus not posted yet</p>
        )}
        {exam.remarks ? <p className="small">📝 {exam.remarks}</p> : null}
        {facultyText(exam) ? <p className="muted small">👤 {facultyText(exam)}</p> : null}
        {isSafeLink(exam.notes_link) ? (
          <a className="student-link" href={exam.notes_link} target="_blank" rel="noopener noreferrer">
            📎 Open notes
          </a>
        ) : null}
      </div>
    </li>
  )
}

function DayGroups({ groups, today }) {
  return groups.map((group) => {
    const badge = today ? relativeDayBadge(today, group.day) : null
    return (
      <div key={group.day} className="day-group">
        <h3 className="day-title">
          {formatDay(group.day)}
          {badge ? <span className={`badge ${badge === 'Today' ? 'badge-today' : 'badge-soon'}`}>{badge}</span> : null}
        </h3>
        <ul className="card-list">
          {group.items.map((exam) => (
            <ExamCard key={exam.id} exam={exam} />
          ))}
        </ul>
      </div>
    )
  })
}

function NoClass({ message }) {
  return (
    <main className="center-screen">
      <div className="card narrow">
        <span className="brand-mark brand-mark-large" aria-hidden="true">
          🎓
        </span>
        <h1 className="screen-title">Open your class's exam list from Discord</h1>
        {message ? <p>{message}</p> : null}
        <p className="muted">
          In your class channel, type <strong>/exams</strong>. The bot replies with the link to your class's upcoming exams.
        </p>
      </div>
    </main>
  )
}

export default function StudentApp() {
  const [classKey] = useState(() => classKeyFromPath())
  if (!classKey) return <NoClass />
  return <ClassBoard classKey={classKey} />
}

function ClassBoard({ classKey }) {
  const [className, setClassName] = useState('')
  const [notFound, setNotFound] = useState('')
  const [scope, setScope] = useState('upcoming')
  const [courseId, setCourseId] = useState('')
  const [courses, setCourses] = useState([])
  const [list, setList] = useState({ exams: [], hasMore: false, today: null })
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let ignore = false
    publicApi(classKey).then(
      (result) => {
        if (ignore) return
        setClassName(result.name)
        document.title = `${result.name} · Exams`
      },
      (loadError) => !ignore && loadError.status === 404 && setNotFound(loadError.message),
    )
    publicApi(classKey, '/courses').then(
      (result) => !ignore && setCourses(result.courses),
      () => {}, // the filter is optional; the exam list reports connection problems
    )
    return () => {
      ignore = true
    }
  }, [classKey, reloadKey])

  useEffect(() => {
    let ignore = false // a slower, older response must not overwrite a newer one
    const course = courseId ? `&course_id=${courseId}` : ''
    publicApi(classKey, `/exams?scope=${scope}&limit=${PAGE_SIZE}&offset=0${course}`).then(
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
  }, [classKey, scope, courseId, reloadKey])

  // Students often leave the tab open; refresh when they come back to it.
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === 'visible') setReloadKey((key) => key + 1)
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  function reload() {
    setLoading(true)
    setError('')
    setReloadKey((key) => key + 1)
  }

  function changeScope(value) {
    if (value === scope) return
    setLoading(true)
    setError('')
    setScope(value)
  }

  function changeCourse(value) {
    setLoading(true)
    setError('')
    setCourseId(value)
  }

  async function loadMore() {
    setLoadingMore(true)
    try {
      const course = courseId ? `&course_id=${courseId}` : ''
      const result = await publicApi(classKey, `/exams?scope=${scope}&limit=${PAGE_SIZE}&offset=${list.exams.length}${course}`)
      setList((current) => ({ ...current, exams: [...current.exams, ...result.exams], hasMore: result.has_more }))
    } catch (loadError) {
      setError(`Could not load more: ${loadError.message}`)
    } finally {
      setLoadingMore(false)
    }
  }

  const selectedCourse = courses.find((c) => String(c.id) === courseId)

  if (notFound) return <NoClass message={notFound} />

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            🎓
          </span>
          <div>
            <p className="eyebrow">AI CR · Exam board</p>
            <p className="brand-name">{className || 'Your class'}</p>
          </div>
        </div>
      </header>

      <main className="app-main student-main" id="main">
        <section aria-labelledby="board-title">
          <div className="student-hero">
            <h1 id="board-title" className="section-title">
              {scope === 'upcoming' ? 'Upcoming exams' : 'Past exams'}
            </h1>
            <p className="muted">
              Dates, times and syllabus as posted by your class representatives. Weeks run Sunday to Thursday,
              Bangladesh time.
            </p>
          </div>

          <div className="student-controls">
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
            <label className="student-filter">
              <span className="visually-hidden">Course</span>
              <select value={courseId} onChange={(event) => changeCourse(event.target.value)} aria-label="Course">
                <option value="">All courses</option>
                {courses.map((course) => (
                  <option key={course.id} value={String(course.id)}>
                    {course.code} · {course.title}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error ? <Banner onRetry={reload}>{error}</Banner> : null}
          {loading ? <LoadingBlock label="Loading exams…" /> : null}

          {!loading && !error && list.exams.length === 0 ? (
            <EmptyState title={scope === 'upcoming' ? 'No upcoming exams posted' : 'No past exams'}>
              {scope === 'upcoming'
                ? `Nothing has been posted${selectedCourse ? ` for ${selectedCourse.code}` : ''} yet. If you think that's wrong, check with your CR.`
                : null}
            </EmptyState>
          ) : null}

          {!loading && scope === 'upcoming' && list.today
            ? groupByWeek(list.exams, list.today).map((week) => (
                <div key={week.label} className="week-group">
                  <h2 className="week-title">{week.label}</h2>
                  <DayGroups groups={week.days} today={list.today} />
                </div>
              ))
            : null}
          {!loading && scope === 'past' ? <DayGroups groups={groupByDay(list.exams)} today={null} /> : null}

          {list.hasMore && !loading ? (
            <button type="button" className="btn btn-ghost btn-block" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? <Spinner label="Loading more…" /> : null}
              Load more
            </button>
          ) : null}
        </section>

        <footer className="student-footer">
          <p>
            Have a question? Ask in your class channel on Discord: <strong>/ask</strong>, <strong>/next-exam-day-update</strong>,{' '}
            <strong>/next-week-update</strong>…
          </p>
          <p className="muted small">
            This list is read-only. Spotted a mistake? Tell your CR. · <a href="/privacy.html">Privacy</a>
          </p>
        </footer>
      </main>
    </div>
  )
}
