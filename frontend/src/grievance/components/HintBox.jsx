import { Lightbulb, X } from 'lucide-react'
import { Card } from './ui'

/** "This may help" box above the submit button. Plain text only; clearly labelled as automated. */
export function HintBox({ hint, onDismiss }) {
  if (!hint) return null
  return (
    <Card className="space-y-2 border-sky-400/30">
      <div className="flex items-start gap-2">
        <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-sm font-medium text-sky-100">Before you submit: this may help</p>
          <p className="whitespace-pre-wrap break-words text-sm text-white/90">{hint.answer}</p>
          {hint.sources.length > 0 && (
            <ul className="space-y-0.5 text-xs text-white/60">
              {hint.sources.map((s) => (
                <li key={s.title + s.section}>
                  Source: {s.url ? <a className="underline" href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> : s.title}
                  {s.section ? `, ${s.section}` : ''}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-white/50">Automated suggestion from the college assistant. It may be wrong. You can still submit your problem.</p>
        </div>
        <button type="button" onClick={onDismiss} aria-label="Hide this suggestion" className="rounded p-1 hover:bg-white/10">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </Card>
  )
}
