import { useState } from 'react'
import { api } from '../lib/api.js'
import { ConfirmDialog, EmptyState, Spinner } from './ui.jsx'

export default function FacultyView({ data, notify, reloadCatalog }) {
  const [name, setName] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState('')
  const [renaming, setRenaming] = useState(null) // { id, name }
  const [savingRename, setSavingRename] = useState(false)
  const [pendingRemove, setPendingRemove] = useState(null)
  const [removing, setRemoving] = useState(false)

  const usage = new Map()
  for (const course of data.courses) {
    for (const member of course.faculty) usage.set(member.id, [...(usage.get(member.id) ?? []), course.code])
  }

  async function add(event) {
    event.preventDefault()
    if (adding || name.trim().length < 2) return
    setAdding(true)
    setAddError('')
    try {
      const created = await api('/api/faculty', { method: 'POST', body: { name } })
      notify(`Added ${created.name}.`)
      setName('')
      await reloadCatalog()
    } catch (error) {
      setAddError(error.message)
    } finally {
      setAdding(false)
    }
  }

  async function saveRename(event) {
    event.preventDefault()
    if (savingRename) return
    setSavingRename(true)
    try {
      const saved = await api(`/api/faculty/${renaming.id}`, { method: 'PATCH', body: { name: renaming.name } })
      notify(`Renamed to ${saved.name}.`)
      setRenaming(null)
      await reloadCatalog()
    } catch (error) {
      notify(`Could not rename: ${error.message}`, 'error')
    } finally {
      setSavingRename(false)
    }
  }

  async function confirmRemove() {
    setRemoving(true)
    try {
      const { result } = await api(`/api/faculty/${pendingRemove.id}`, { method: 'DELETE' })
      notify(result === 'archived' ? `${pendingRemove.name} removed (kept on past exam records).` : `${pendingRemove.name} removed.`)
      setPendingRemove(null)
      await reloadCatalog()
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setRemoving(false)
    }
  }

  return (
    <section aria-labelledby="faculty-title">
      <h1 id="faculty-title" className="section-title">
        Faculty
      </h1>
      <p className="muted section-lead">One list for the whole term. Assign people to courses from the Courses tab.</p>

      <form className="card inline-add-card" onSubmit={add} noValidate>
        <label htmlFor="faculty-name" className="field-label">
          Add faculty member
        </label>
        <div className="inline-add">
          <input
            id="faculty-name"
            type="text"
            maxLength={120}
            placeholder="Full name"
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setAddError('')
            }}
            aria-invalid={Boolean(addError)}
          />
          <button type="submit" className="btn btn-primary" disabled={adding || name.trim().length < 2}>
            {adding ? <Spinner label="Adding…" /> : null}
            Add
          </button>
        </div>
        {addError ? (
          <p className="field-error" role="alert">
            {addError}
          </p>
        ) : null}
      </form>

      {data.faculty.length === 0 ? (
        <EmptyState title="No faculty yet">Add the teachers for this term's courses.</EmptyState>
      ) : (
        <ul className="card-list">
          {data.faculty.map((member) => (
            <li key={member.id} className="card faculty-card">
              {renaming?.id === member.id ? (
                <form className="inline-add grow" onSubmit={saveRename}>
                  <label htmlFor={`rename-${member.id}`} className="visually-hidden">
                    New name for {member.name}
                  </label>
                  <input
                    id={`rename-${member.id}`}
                    type="text"
                    maxLength={120}
                    value={renaming.name}
                    onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
                  />
                  <button type="submit" className="btn btn-primary btn-small" disabled={savingRename || renaming.name.trim().length < 2}>
                    Save
                  </button>
                  <button type="button" className="btn btn-ghost btn-small" onClick={() => setRenaming(null)}>
                    Cancel
                  </button>
                </form>
              ) : (
                <>
                  <div className="grow">
                    <p className="faculty-name">{member.name}</p>
                    <p className="muted small">{usage.get(member.id)?.join(', ') ?? 'Not assigned to a course'}</p>
                  </div>
                  <div className="card-actions">
                    <button type="button" className="btn btn-ghost btn-small" onClick={() => setRenaming({ id: member.id, name: member.name })}>
                      Rename
                    </button>
                    <button type="button" className="btn btn-danger-ghost btn-small" onClick={() => setPendingRemove(member)}>
                      Remove
                    </button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={Boolean(pendingRemove)}
        title={`Remove ${pendingRemove?.name ?? ''}?`}
        confirmLabel="Remove"
        busy={removing}
        onConfirm={confirmRemove}
        onCancel={() => setPendingRemove(null)}
      >
        {usage.get(pendingRemove?.id) ? (
          <p>They teach {usage.get(pendingRemove.id).join(', ')}. Remove them from those courses first.</p>
        ) : (
          <p>They will disappear from the faculty list. Past exam records that mention them are kept.</p>
        )}
      </ConfirmDialog>
    </section>
  )
}
