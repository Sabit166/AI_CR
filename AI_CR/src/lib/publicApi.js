// Read-only client for a class's exam board. No sign-in: it only calls /api/public/classes/<key>/*.
// Each class's board lives at /c/<key>; the Discord bot shares that link with /exams.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001').replace(/\/$/, '')

const KEY_RE = /^\/c\/([0-9a-f-]{36})\/?$/i

export function classKeyFromPath(pathname = window.location.pathname) {
  return pathname.match(KEY_RE)?.[1] ?? null
}

export async function publicApi(classKey, path = '', { signal } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/public/classes/${classKey}${path}`, { signal })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Could not reach the server. Check your connection and try again.', { cause: error })
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    const error = new Error(detail?.message ?? (typeof detail === 'string' ? detail : `Request failed (${response.status})`))
    error.status = response.status
    throw error
  }
  return payload
}
