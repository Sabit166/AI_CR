import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { api, ApiError } from './lib/api.js'
import { supabase, supabaseConfigured } from './lib/supabase.js'
import LoginScreen from './components/LoginScreen.jsx'
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

function App() {
  const [session, setSession] = useState(undefined) // undefined = still checking
  const [authState, setAuthState] = useState({ status: 'idle', message: '' })
  const [tab, setTab] = useState(initialTab)
  const [data, setData] = useState({ config: null, courses: [], faculty: [] })
  const [dataState, setDataState] = useState({ loading: true, error: '' })
  const { toasts, notify, dismiss } = useToasts()

  useEffect(() => {
    if (!supabaseConfigured) return undefined
    supabase.auth.getSession().then(({ data: result }) => setSession(result.session))
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession))
    return () => listener.subscription.unsubscribe()
  }, [])

  const [reloadKey, setReloadKey] = useState(0)
  const userId = session?.user?.id

  useEffect(() => {
    if (!userId) return undefined
    let ignore = false
    Promise.all([api('/api/config'), api('/api/courses'), api('/api/faculty')]).then(
      ([config, courses, faculty]) => {
        if (ignore) return
        setData({ config, courses: courses.courses, faculty: faculty.faculty })
        setAuthState({ status: 'ok', message: '' })
        setDataState({ loading: false, error: '' })
      },
      (error) => {
        if (ignore) return
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setAuthState({ status: error.status === 403 ? 'forbidden' : 'expired', message: error.message })
        }
        setDataState({ loading: false, error: error.message })
      },
    )
    return () => {
      ignore = true
    }
  }, [userId, reloadKey])

  const reloadCatalog = useCallback(async () => {
    try {
      const [courses, faculty] = await Promise.all([api('/api/courses'), api('/api/faculty')])
      setData((current) => ({ ...current, courses: courses.courses, faculty: faculty.faculty }))
    } catch (error) {
      notify(`Saved, but refreshing the list failed: ${error.message}`, 'error')
    }
  }, [notify])

  function selectTab(id) {
    setTab(id)
    window.history.replaceState(null, '', `#${id}`)
  }

  async function signOut() {
    await supabase.auth.signOut()
    setData({ config: null, courses: [], faculty: [] })
    setAuthState({ status: 'idle', message: '' })
  }

  if (!supabaseConfigured) {
    return (
      <main className="center-screen">
        <Banner>
          Sign-in is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY for the dashboard build.
        </Banner>
      </main>
    )
  }

  if (session === undefined) {
    return (
      <main className="center-screen">
        <LoadingBlock label="Checking sign-in…" />
      </main>
    )
  }

  if (!session) {
    return <LoginScreen />
  }

  if (authState.status === 'forbidden' || authState.status === 'expired') {
    return (
      <main className="center-screen">
        <div className="card narrow">
          <h1 className="screen-title">{authState.status === 'forbidden' ? 'Not a CR account' : 'Session expired'}</h1>
          <p>{authState.message}</p>
          <p className="muted">Signed in as {session.user.email}</p>
          <button type="button" className="btn btn-primary btn-block" onClick={signOut}>
            Sign out
          </button>
        </div>
      </main>
    )
  }

  const shared = { data, notify, reloadCatalog }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            CR
          </span>
          <div>
            <p className="eyebrow">AI CR dashboard</p>
            <p className="brand-name">Class exam updates</p>
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
        <button type="button" className="btn btn-ghost btn-small" onClick={signOut}>
          Sign out
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
        {dataState.loading && !data.config ? <LoadingBlock label="Loading your courses…" /> : null}
        {data.config ? (
          <>
            {tab === 'exams' ? <ExamsView {...shared} goToCourses={() => selectTab('courses')} /> : null}
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
