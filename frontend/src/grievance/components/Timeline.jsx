import { formatDateTime } from '../lib/format'
import { Badge } from './ui'

/** The history of a ticket, oldest first. 'internal' events are only sent to staff. */
export function Timeline({ events }) {
  if (!events?.length) return null
  return (
    <ol className="relative space-y-4 border-l border-white/15 pl-5" aria-label="History">
      {events.map((e, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full bg-purple-400" aria-hidden="true" />
          <p className="text-xs text-white/50">
            {e.actor} · {formatDateTime(e.created_at)}
            {e.internal && <> · <Badge tone="slate">internal</Badge></>}
          </p>
          {e.text && <p className="whitespace-pre-wrap break-words text-sm text-white/90">{e.text}</p>}
        </li>
      ))}
    </ol>
  )
}
