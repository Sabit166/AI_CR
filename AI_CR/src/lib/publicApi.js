// Read-only client for the student board. No sign-in and no Supabase: it only calls /api/public/*.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001').replace(/\/$/, '')

export const MESSENGER_URL = import.meta.env.VITE_MESSENGER_URL || 'https://m.me/61592083183113'

export async function publicApi(path, { signal } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/public${path}`, { signal })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Could not reach the server. Check your connection and try again.', { cause: error })
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    throw new Error(detail?.message ?? (typeof detail === 'string' ? detail : `Request failed (${response.status})`))
  }
  return payload
}
