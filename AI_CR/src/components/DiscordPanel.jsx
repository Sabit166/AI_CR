import { useState } from 'react'
import { api } from '../lib/api.js'
import { ConfirmDialog, Spinner } from './ui.jsx'

const POSTS = [
  { kind: 'this_week', label: 'This week', title: "Post this week's exams?" },
  { kind: 'next_week', label: 'Next week', title: "Post next week's exams?" },
  { kind: 'next_exam_day', label: 'Next exam day', title: 'Post the next exam day?' },
  { kind: 'next_exam_notes', label: 'Next exam notes', title: 'Post the next exam notes?' },
]

export default function DiscordPanel({ classInfo, notify, setClassInfo }) {
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const [savingAuto, setSavingAuto] = useState(false)

  async function post() {
    setBusy(true)
    try {
      const result = await api('/api/discord/post', { method: 'POST', body: { kind: pending.kind } })
      const exams = result.exam_count === 1 ? '1 exam' : `${result.exam_count} exams`
      notify(`Posted to Discord (${exams}).`)
      setPending(null)
    } catch (error) {
      notify(`Not posted: ${error.message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function toggleAuto() {
    setSavingAuto(true)
    try {
      const result = await api('/api/class', { method: 'PATCH', body: { auto_updates: !classInfo.auto_updates } })
      setClassInfo(result.class)
      notify(result.class.auto_updates ? 'Automatic updates are on.' : 'Automatic updates are off.')
    } catch (error) {
      notify(`Could not change it: ${error.message}`, 'error')
    } finally {
      setSavingAuto(false)
    }
  }

  if (!classInfo.linked) {
    return (
      <div className="card discord-panel">
        <p className="discord-title">Post to Discord</p>
        <p className="muted small">This class isn't linked to a Discord channel yet. Run /setup in the channel.</p>
      </div>
    )
  }

  return (
    <div className="card discord-panel">
      <div className="discord-head">
        <p className="discord-title">Post to the class channel</p>
        <a href={classInfo.board_url} target="_blank" rel="noopener noreferrer">
          Student view ↗
        </a>
      </div>
      <div className="discord-buttons">
        {POSTS.map((item) => (
          <button key={item.kind} type="button" className="btn btn-ghost btn-small" onClick={() => setPending(item)}>
            📣 {item.label}
          </button>
        ))}
      </div>
      <label className="discord-auto">
        <input type="checkbox" checked={classInfo.auto_updates} onChange={toggleAuto} disabled={savingAuto} />
        <span>
          Automatic updates
          <span className="muted small"> — next week's exams every Friday evening, and a reminder the evening before each exam day</span>
        </span>
        {savingAuto ? <Spinner label="Saving…" /> : null}
      </label>

      <ConfirmDialog
        open={Boolean(pending)}
        title={pending?.title ?? ''}
        confirmLabel="Post"
        tone="primary"
        busy={busy}
        onConfirm={post}
        onCancel={() => setPending(null)}
      >
        <p>Everyone in the class channel will see it.</p>
      </ConfirmDialog>
    </div>
  )
}
