const dateTime = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' })

/** The API sends UTC timestamps, sometimes without a 'Z'. Treat them as UTC. */
export function parseDate(value) {
  if (!value) return null
  const s = String(value)
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z')
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDateTime(value) {
  const d = parseDate(value)
  return d ? dateTime.format(d) : ''
}

function span(ms) {
  const mins = Math.round(ms / 60000)
  if (mins < 1) return 'less than a minute'
  if (mins < 60) return `${mins} min`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} h`
  return `${Math.round(hours / 24)} days`
}

/** { text: 'due in 5 h' | 'overdue by 2 days', overdue: boolean } */
export function timeUntil(value, now = new Date()) {
  const d = parseDate(value)
  if (!d) return { text: '', overdue: false }
  const diff = d.getTime() - now.getTime()
  return diff >= 0
    ? { text: `due in ${span(diff)}`, overdue: false }
    : { text: `overdue by ${span(-diff)}`, overdue: true }
}

export function shortText(text, max = 90) {
  const t = (text || '').replace(/\s+/g, ' ').trim()
  return t.length > max ? t.slice(0, max - 1) + '…' : t
}
