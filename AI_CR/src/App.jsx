import { useEffect, useMemo, useState } from 'react'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001'

const EMPTY_EXAM = {
  'Course Code': '',
  'Course Title': '',
  'Course Teacher': '',
  'Course Section': '',
  'Exam Type': '',
  'Exam Day': '',
  'Exam Date': '',
  'Syllabus': '',
  'Exam Notes Drive Link': '',
}

const TABLE_COLUMNS = [
  'id',
  'Course Code',
  'Course Title',
  'Course Teacher',
  'Course Section',
  'Exam Type',
  'Exam Day',
  'Exam Date',
  'Syllabus',
  'Exam Notes Drive Link',
]

function App() {
  const [records, setRecords] = useState([])
  const [newRecord, setNewRecord] = useState(EMPTY_EXAM)
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const totalRows = useMemo(() => records.length, [records])

  useEffect(() => {
    loadRecords()
  }, [])

  async function loadRecords() {
    setLoading(true)
    setError('')

    try {
      const response = await fetch(`${API_BASE_URL}/exams`)
      if (!response.ok) {
        throw new Error(`Failed to load records (${response.status})`)
      }
      const data = await response.json()
      setRecords((data.records ?? []).map((record) => ({ ...record })))
    } catch (fetchError) {
      setError(fetchError.message)
    } finally {
      setLoading(false)
    }
  }

  function updateExistingRecord(id, field, value) {
    setRecords((current) =>
      current.map((record) => (record.id === id ? { ...record, [field]: value } : record)),
    )
  }

  function updateNewRecord(field, value) {
    setNewRecord((current) => ({ ...current, [field]: value }))
  }

  async function saveRecord(record) {
    setSavingId(record.id)
    setMessage('')
    setError('')

    const payload = {
      'Course Code': record['Course Code'] ?? '',
      'Course Title': record['Course Title'] ?? '',
      'Course Teacher': record['Course Teacher'] ?? '',
      'Course Section': record['Course Section'] ?? '',
      'Exam Type': record['Exam Type'] ?? '',
      'Exam Day': record['Exam Day'] ?? '',
      'Exam Date': record['Exam Date'] ?? '',
      Syllabus: record.Syllabus ?? '',
      'Exam Notes Drive Link': record['Exam Notes Drive Link'] ?? '',
    }

    try {
      const response = await fetch(`${API_BASE_URL}/exams/${record.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}))
        throw new Error(errorBody.detail ?? `Failed to update row (${response.status})`)
      }

      setMessage(`Row ${record.id} updated.`)
      await loadRecords()
    } catch (updateError) {
      setError(updateError.message)
    } finally {
      setSavingId(null)
    }
  }

  async function createRecord(event) {
    event.preventDefault()
    setMessage('')
    setError('')

    try {
      const response = await fetch(`${API_BASE_URL}/exams`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newRecord),
      })

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}))
        throw new Error(errorBody.detail ?? `Failed to insert row (${response.status})`)
      }

      setNewRecord(EMPTY_EXAM)
      setMessage('New row inserted.')
      await loadRecords()
    } catch (createError) {
      setError(createError.message)
    }
  }

  async function deleteRecord(id) {
    const confirmed = window.confirm(`Delete row ${id}?`)
    if (!confirmed) {
      return
    }

    setSavingId(id)
    setMessage('')
    setError('')

    try {
      const response = await fetch(`${API_BASE_URL}/exams/${id}`, {
        method: 'DELETE',
      })

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}))
        throw new Error(errorBody.detail ?? `Failed to delete row (${response.status})`)
      }

      setMessage(`Row ${id} deleted.`)
      await loadRecords()
    } catch (deleteError) {
      setError(deleteError.message)
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div className="dashboard-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">S</div>
          <div>
            <p className="eyebrow">Student dashboard</p>
            <h1>Exams</h1>
          </div>
        </div>

        <nav className="sidebar-nav">
          <a href="#overview" className="nav-item active">
            Overview
          </a>
          <a href="#add-row" className="nav-item">
            Add row
          </a>
          <a href="#records" className="nav-item">
            Records
          </a>
        </nav>

        <div className="sidebar-note">
          <span>Source table</span>
          <strong>Supabase Exams</strong>
          <small>Inline edits, insert, refresh, delete</small>
        </div>
      </aside>

      <main className="content-shell">
        <header className="topbar" id="overview">
          <div>
            <p className="eyebrow">Academic records</p>
            <h2>Manage the full Exams table from one clean screen.</h2>
            <p className="intro">
              This layout keeps the table visible like a dashboard: quick stats on top, form on the left, and a wide editable grid below.
            </p>
          </div>

          <div className="stats-row">
            <div className="stat-card">
              <span>Total rows</span>
              <strong>{totalRows}</strong>
            </div>
            <div className="stat-card alt">
              <span>Status</span>
              <strong>{loading ? 'Loading' : 'Ready'}</strong>
            </div>
          </div>
        </header>

        <section className="grid-layout">
          <section className="panel form-panel" id="add-row">
            <div className="panel-header compact">
              <div>
                <h3>Add row</h3>
                <p>Insert a new exam record.</p>
              </div>
            </div>

            <form className="record-form" onSubmit={createRecord}>
              {Object.keys(EMPTY_EXAM).map((field) => (
                <label key={field}>
                  <span>{field}</span>
                  <input
                    type={field === 'Exam Date' ? 'datetime-local' : 'text'}
                    value={newRecord[field]}
                    onChange={(event) => updateNewRecord(field, event.target.value)}
                    placeholder={field}
                  />
                </label>
              ))}
              <button type="submit" className="primary-button">
                Insert row
              </button>
            </form>
          </section>

          <section className="panel table-panel" id="records">
            <div className="panel-header">
              <div>
                <h3>Records</h3>
                <p>Scroll sideways to view every column. Save updates row by row.</p>
              </div>
              <button type="button" className="secondary-button" onClick={loadRecords}>
                Refresh
              </button>
            </div>

            {message ? <p className="status success">{message}</p> : null}
            {error ? <p className="status error">{error}</p> : null}
            {loading ? <p className="status muted">Loading records...</p> : null}

            {!loading ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {TABLE_COLUMNS.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((record) => (
                      <tr key={record.id}>
                        <td className="id-cell">{record.id}</td>
                        {TABLE_COLUMNS.slice(1).map((column) => (
                          <td key={column}>
                            <input
                              type={column === 'Exam Date' ? 'datetime-local' : 'text'}
                              value={record[column] ?? ''}
                              onChange={(event) => updateExistingRecord(record.id, column, event.target.value)}
                            />
                          </td>
                        ))}
                        <td>
                          <div className="actions">
                            <button
                              type="button"
                              className="primary-button small"
                              onClick={() => saveRecord(record)}
                              disabled={savingId === record.id}
                            >
                              {savingId === record.id ? 'Saving...' : 'Save'}
                            </button>
                            <button
                              type="button"
                              className="danger-button small"
                              onClick={() => deleteRecord(record.id)}
                              disabled={savingId === record.id}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </section>
      </main>
    </div>
  )
}

export default App
