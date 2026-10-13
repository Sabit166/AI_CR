import { useState } from 'react'
import { supabase } from '../lib/supabase.js'
import { Field, Spinner } from './ui.jsx'

export default function LoginScreen() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    const { error: signInError } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
    if (signInError) {
      setError(signInError.message === 'Invalid login credentials' ? 'Wrong email or password.' : signInError.message)
      setBusy(false)
    }
    // On success the auth listener in App swaps this screen out.
  }

  return (
    <main className="center-screen">
      <form className="card narrow" onSubmit={submit} noValidate>
        <span className="brand-mark brand-mark-large" aria-hidden="true">
          CR
        </span>
        <h1 className="screen-title">Sign in</h1>
        <p className="muted">For class representatives managing courses and exam updates.</p>

        <Field label="Email" htmlFor="login-email" required>
          <input
            id="login-email"
            type="email"
            autoComplete="username"
            inputMode="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </Field>
        <Field label="Password" htmlFor="login-password" required error={error}>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? 'login-password-error' : undefined}
            required
          />
        </Field>

        <button type="submit" className="btn btn-primary btn-block" disabled={busy || !email || !password}>
          {busy ? <Spinner label="Signing in…" /> : null}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
