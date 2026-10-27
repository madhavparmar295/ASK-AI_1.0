import { HINT_URL } from '../config'

/**
 * Ask the chatbot for a helpful answer before the student submits. Returns null when the hint is switched
 * off, when there is nothing useful, or when anything goes wrong: a hint must never get in the way.
 * Expected answer: { answer: string, sources?: [{ title, url?, section? }] }
 */
export async function fetchHint(text, { signal, url = HINT_URL, fetchImpl = (...a) => fetch(...a) } = {}) {
  if (!url) return null
  const timeout = new AbortController()
  // The server gives up at 12 s (GRIEVANCE_HINT_TIMEOUT_SECONDS). Wait a little
  // longer than that so a late-but-real answer still arrives instead of being cut
  // off by the browser. The student is still writing, so 13 s is not "too late".
  const timer = setTimeout(() => timeout.abort(), 13000)
  const onAbort = () => timeout.abort()
  signal?.addEventListener('abort', onAbort)
  try {
    const res = await fetchImpl(url, {
      method: 'POST', credentials: 'include', signal: timeout.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) return null
    const data = await res.json()
    const answer = typeof data?.answer === 'string' ? data.answer.trim() : ''
    if (!answer) return null
    const sources = Array.isArray(data.sources)
      ? data.sources.filter((s) => s && typeof s.title === 'string').slice(0, 5)
          .map((s) => ({ title: s.title, section: typeof s.section === 'string' ? s.section : '', url: /^https?:\/\//.test(s.url || '') || String(s.url || '').startsWith('/') ? s.url : '' }))
      : []
    return { answer: answer.slice(0, 2000), sources }
  } catch {
    return null
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}
