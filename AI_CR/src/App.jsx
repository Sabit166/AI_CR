import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { api, ApiError } from './lib/api.js'
import { editorToken, forgetToken } from './lib/session.js'
import ExamsView from './components/ExamsView.jsx'
import CoursesView from './components/CoursesView.jsx'
import FacultyView from './components/FacultyView.jsx'
import { Banner, LoadingBlock, Toasts } from './components/ui.jsx'

const TABS = [
  { id: 'exams', label: 'Exams', icon: '🗓' },
  { id: 'courses', label: 'Courses', icon: '📘' },
  { id: 'faculty', label: 'Faculty', icon: '👤' },
]

function useToasts() {
  const [toasts, setToasts] = useState([])
  const nextId = useRef(1)
  const dismiss = useCallback((id) => setToasts((current) => current.filter((t) => t.id !== id)), [])
  const notify = useCallback(
    (message, kind = 'success') => {
      const id = nextId.current++
      setToasts((current) => [...current.slice(-2), { id, message, kind }])
      setTimeout(() => dismiss(id), kind === 'error' ? 8000 : 4000)
    },
    [dismiss],
  )
  return { toasts, notify, dismiss }
}

function initialTab() {
  const hash = window.location.hash.replace('#', '')
  return TABS.some((tab) => tab.id === hash) ? hash : 'exams'
}

function LinkScreen({ title, children }) {
  return (
    <main className="center-screen">
      <div className="card narrow">
        <span className="brand-mark brand-mark-large" aria-hidden="true">
          CR
        </span>
        <h1 className="screen-title">{title}</h1>
        {children}
        <p className="muted">
          In your class's Discord channel, type <strong>/manage</strong>. The bot sends you a private link that opens
          this editor for that class. Only CRs get the link.
        </p>
      </div>
    </main>
  )
}

function App() {
  const [hasToken] = useState(() => Boolean(editorToken()))
  const [linkState, setLinkState] = useState({ status: 'ok', message: '' })
  const [tab, setTab] = useState(initialTab)
  const [data, setData] = useState({ config: null, courses: [], faculty: [] })
  const [dataState, setDataState] = useState({ loading: true, error: '' })
  const { toasts, notify, dismiss } = useToasts()
  const [reloadKey, setReloadKey] = useState(0)

  const handleAuthError = useCallback((error) => {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      forgetToken()
      setLinkState({ status: 'expired', message: error.message })
      return true
    }
    return false
  }, [])

  useEffect(() => {
    if (!hasToken) return undefined
    let ignore = false
    Promise.all([api('/api/config'), api('/api/courses'), api('/api/faculty')]).then(
      ([config, courses, faculty]) => {
        if (ignore) return
        setData({ config, courses: courses.courses, faculty: faculty.faculty })
        setDataState({ loading: false, error: '' })
      },
      (error) => {
        if (ignore) return
        handleAuthError(error)
        setDataState({ loading: false, error: error.message })
      },
    )
    return () => {
      ignore = true
    }
  }, [hasToken, reloadKey, handleAuthError])

  const reloadCatalog = useCallback(async () => {
    try {
      const [courses, faculty] = await Promise.all([api('/api/courses'), api('/api/faculty')])
      setData((current) => ({ ...current, courses: courses.courses, faculty: faculty.faculty }))
    } catch (error) {
      if (!handleAuthError(error)) notify(`Saved, but refreshing the list failed: ${error.message}`, 'error')
    }
  }, [notify, handleAuthError])

  const setClassInfo = useCallback(
    (info) => setData((current) => ({ ...current, config: { ...current.config, class: info } })),
    [],
  )

  function selectTab(id) {
    setTab(id)
    window.history.replaceState(null, '', `#${id}`)
  }

  function leave() {
    forgetToken()
    setLinkState({ status: 'left', message: '' })
  }

  if (!hasToken || linkState.status === 'left') {
    return (
      <LinkScreen title="Open the editor from Discord">
        {linkState.status === 'left' ? <p>You closed the editor on this device.</p> : null}
      </LinkScreen>
    )
  }

  if (linkState.status === 'expired') {
    return (
      <LinkScreen title="This link has expired">
        <p>{linkState.message}</p>
      </LinkScreen>
    )
  }

  const classInfo = data.config?.class
  const shared = { data, notify, reloadCatalog, onAuthError: handleAuthError }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            CR
          </span>
          <div className="grow">
            <p className="eyebrow">CR editor</p>
            <p className="brand-name">{classInfo?.name ?? 'Class exam updates'}</p>
          </div>
        </div>
        <nav className="tabs-top" aria-label="Sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`tab${tab === item.id ? ' tab-active' : ''}`}
              aria-current={tab === item.id ? 'page' : undefined}
              onClick={() => selectTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <button type="button" className="btn btn-ghost btn-small" onClick={leave}>
          Close
        </button>
      </header>

      <main className="app-main" id="main">
        {dataState.error && !dataState.loading ? (
          <Banner
            onRetry={() => {
              setDataState({ loading: true, error: '' })
              setReloadKey((key) => key + 1)
            }}
          >
            {dataState.error}
          </Banner>
        ) : null}
        {dataState.loading && !data.config ? <LoadingBlock label="Loading your class…" /> : null}
        {data.config ? (
          <>
            {tab === 'exams' ? (
              <ExamsView {...shared} setClassInfo={setClassInfo} goToCourses={() => selectTab('courses')} />
            ) : null}
            {tab === 'courses' ? <CoursesView {...shared} goToFaculty={() => selectTab('faculty')} /> : null}
            {tab === 'faculty' ? <FacultyView {...shared} /> : null}
          </>
        ) : null}
      </main>

      <nav className="tabs-bottom" aria-label="Sections">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`bottom-tab${tab === item.id ? ' bottom-tab-active' : ''}`}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => selectTab(item.id)}
          >
            <span aria-hidden="true">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      <Toasts toasts={toasts} onDismiss={dismiss} />
    </div>
  )
}

export default App
