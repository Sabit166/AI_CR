import { useEffect, useId, useRef } from 'react'

export function Spinner({ label = 'Loading…' }) {
  return (
    <span className="spinner-wrap" role="status">
      <span className="spinner" aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  )
}

export function LoadingBlock({ label = 'Loading…' }) {
  return (
    <div className="loading-block">
      <Spinner label={label} />
      <span aria-hidden="true">{label}</span>
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  )
}

export function Banner({ kind = 'error', children, onRetry }) {
  return (
    <div className={`banner banner-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <span>{children}</span>
      {onRetry ? (
        <button type="button" className="btn btn-ghost btn-small" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  )
}

export function Toasts({ toasts, onDismiss }) {
  return (
    <div className="toast-region" aria-live="polite" aria-atomic="false">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.kind}`} role={toast.kind === 'error' ? 'alert' : 'status'}>
          <span>{toast.message}</span>
          <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => onDismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  )
}

export function ConfirmDialog({ open, title, children, confirmLabel = 'Delete', busy = false, onConfirm, onCancel }) {
  const ref = useRef(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onCancel()
      }}
    >
      <h3 id={titleId}>{title}</h3>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy}>
          {busy ? <Spinner label="Working…" /> : null}
          {confirmLabel}
        </button>
      </div>
    </dialog>
  )
}

export function Field({ label, htmlFor, hint, error, required, children }) {
  return (
    <div className={`field${error ? ' field-invalid' : ''}`}>
      <label htmlFor={htmlFor} className="field-label">
        {label}
        {required ? <span className="required" aria-hidden="true"> *</span> : null}
      </label>
      {children}
      {hint && !error ? (
        <p className="field-hint" id={`${htmlFor}-hint`}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="field-error" id={`${htmlFor}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export function TypeBadge({ type }) {
  if (!type) return null
  return <span className={`badge badge-${type === 'Sessional' ? 'sessional' : 'theory'}`}>{type}</span>
}

// Single-choice chips (radio semantics) — big touch targets instead of a <select>.
export function ChipGroup({ legend, name, options, value, onChange, error, required, describedBy }) {
  return (
    <fieldset className={`chip-group${error ? ' field-invalid' : ''}`} aria-describedby={describedBy}>
      <legend className="field-label">
        {legend}
        {required ? <span className="required" aria-hidden="true"> *</span> : null}
      </legend>
      <div className="chips">
        {options.map((option) => (
          <label key={option.value} className={`chip${value === option.value ? ' chip-selected' : ''}`}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span className="chip-text">
              {option.label}
              {option.sub ? <small>{option.sub}</small> : null}
            </span>
          </label>
        ))}
      </div>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  )
}

export function CheckList({ legend, options, selected, onToggle, emptyText, error, hint }) {
  return (
    <fieldset className={`check-list${error ? ' field-invalid' : ''}`}>
      <legend className="field-label">{legend}</legend>
      {options.length === 0 ? <p className="field-hint">{emptyText}</p> : null}
      <div className="checks">
        {options.map((option) => (
          <label key={option.value} className={`check${selected.includes(option.value) ? ' check-selected' : ''}`}>
            <input type="checkbox" checked={selected.includes(option.value)} onChange={() => onToggle(option.value)} />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
      {hint && !error ? <p className="field-hint">{hint}</p> : null}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  )
}
