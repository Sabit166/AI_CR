import { supabase } from './supabase.js'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, { status = 0, field = null, detail = null } = {}) {
    super(message)
    this.status = status
    this.field = field
    this.detail = detail
  }
}

function errorFromResponse(status, body) {
  const detail = body?.detail
  // FastAPI request-validation errors: [{loc: ['body', 'field'], msg: '...'}]
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0]
    const field = Array.isArray(first.loc) ? first.loc.at(-1) : null
    const message = String(first.msg ?? 'Invalid value').replace(/^Value error, /, '')
    return new ApiError(message, { status, field, detail })
  }
  if (detail && typeof detail === 'object') {
    return new ApiError(detail.message ?? 'Request failed', { status, field: detail.field ?? null, detail })
  }
  if (typeof detail === 'string') return new ApiError(detail, { status })
  return new ApiError(`Request failed (${status})`, { status })
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) throw new ApiError('Please sign in.', { status: 401 })

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      signal,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError('Could not reach the server. Check your connection and try again.')
  }

  const payload = await response.json().catch(() => null)
  if (!response.ok) throw errorFromResponse(response.status, payload)
  return payload
}
