import { API_BASE } from '../config'

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status      // 0 = the server could not be reached
    this.data = data          // the JSON body, e.g. { existing_ticket_id } on a duplicate
  }
}

const DEFAULT_MESSAGES = {
  0: 'Could not reach the server. Check your connection and try again.',
  401: 'Please sign in again.',
  403: 'You are not allowed to do that.',
  404: 'Not found.',
  413: 'That file is too large.',
  415: 'That type of file is not accepted.',
  429: 'Too many requests. Please wait a moment and try again.',
}

/** FastAPI sends detail as a string, or as a list of {msg} for validation errors. */
export function detailToMessage(detail) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => (d && d.msg ? String(d.msg).replace(/^Value error, /, '') : null)).filter(Boolean)
    if (parts.length) return parts.join('; ')
  }
  return null
}

function cookieValue(name) {
  if (typeof document === 'undefined' || !document.cookie) return null
  const hit = document.cookie.split('; ').find((c) => c.startsWith(name + '='))
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null
}

function toQuery(query) {
  const p = new URLSearchParams()
  Object.entries(query || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '' && v !== false) p.set(k, String(v))
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

/**
 * Small fetch wrapper: cookies on, CSRF header on every change, errors as ApiError.
 * fetchImpl can be replaced in tests.
 */
export function createClient({ baseUrl = API_BASE, fetchImpl = (...a) => fetch(...a) } = {}) {
  let csrf = null
  let onUnauthorized = null

  async function request(method, path, { body, form, query, signal, silent401 = false } = {}) {
    const headers = { Accept: 'application/json' }
    const init = { method, headers, credentials: 'include', signal }
    if (form) init.body = form                               // the browser sets the multipart boundary
    else if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
    if (method !== 'GET') {
      const token = csrf || cookieValue('grievance_csrf')
      if (token) headers['X-CSRF-Token'] = token
    }

    let res
    try {
      res = await fetchImpl(baseUrl + path + toQuery(query), init)
    } catch (e) {
      if (e && e.name === 'AbortError') throw e
      throw new ApiError(0, DEFAULT_MESSAGES[0])
    }

    let data = null
    if (res.status !== 204) {
      const type = res.headers.get('content-type') || ''
      try { data = type.includes('json') ? await res.json() : await res.text() } catch { data = null }
    }
    if (res.ok) return data

    const message = detailToMessage(data && data.detail)
      || DEFAULT_MESSAGES[res.status]
      || (res.status >= 500 ? 'Something went wrong on the server. Please try again.' : 'The request could not be completed.')
    if (res.status === 401 && !silent401 && onUnauthorized) onUnauthorized()
    throw new ApiError(res.status, message, data && typeof data === 'object' ? data : null)
  }

  return {
    get: (path, opts) => request('GET', path, opts),
    post: (path, body, opts) => request('POST', path, { ...opts, body }),
    upload: (path, form, opts) => request('POST', path, { ...opts, form }),
    patch: (path, body, opts) => request('PATCH', path, { ...opts, body }),
    del: (path, opts) => request('DELETE', path, opts),
    setCsrf: (token) => { csrf = token || null },
    setOnUnauthorized: (fn) => { onUnauthorized = fn },
    baseUrl,
  }
}
