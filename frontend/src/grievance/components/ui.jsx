import { useEffect, useId, useRef } from 'react'
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from 'lucide-react'
import { statusInfo } from '../lib/status'

// Look and feel: dark, purple accent, frosted glass, to match the chatbot app.
export const inputClass =
  'w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/40 ' +
  'focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50'

export function Card({ className = '', children, ...rest }) {
  return (
    <div className={`rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-md sm:p-5 ${className}`} {...rest}>
      {children}
    </div>
  )
}

const BUTTON = {
  primary: 'bg-purple-600 text-white hover:bg-purple-500 focus-visible:ring-purple-400',
  secondary: 'bg-white/10 text-white hover:bg-white/20 focus-visible:ring-white/40',
  danger: 'bg-red-600/80 text-white hover:bg-red-500 focus-visible:ring-red-400',
  ghost: 'text-white/80 hover:bg-white/10 focus-visible:ring-white/40',
}

export function Button({ variant = 'primary', loading = false, disabled, className = '', children, type = 'button', ...rest }) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition
        focus:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON[variant]} ${className}`}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-white/60">
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

const ALERT = {
  error: { cls: 'border-red-500/40 bg-red-500/10 text-red-100', Icon: XCircle },
  warn: { cls: 'border-amber-500/40 bg-amber-500/10 text-amber-100', Icon: AlertTriangle },
  info: { cls: 'border-sky-500/40 bg-sky-500/10 text-sky-100', Icon: Info },
  success: { cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-100', Icon: CheckCircle2 },
}

export function Alert({ tone = 'info', title, children, className = '' }) {
  const { cls, Icon } = ALERT[tone]
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex gap-3 rounded-xl border p-3 text-sm ${cls} ${className}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div>
        {title && <p className="font-medium">{title}</p>}
        <div>{children}</div>
      </div>
    </div>
  )
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  return (
    <Alert tone="error" title="Something went wrong">
      <p>{error.message}</p>
      {onRetry && <button onClick={onRetry} className="mt-2 underline">Try again</button>}
    </Alert>
  )
}

export function EmptyState({ icon: Icon, title, children }) {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-center text-white/60">
      {Icon && <Icon className="h-8 w-8 text-white/30" aria-hidden="true" />}
      <p className="font-medium text-white/80">{title}</p>
      {children && <p className="max-w-sm text-sm">{children}</p>}
    </div>
  )
}

export function Field({ label, hint, error, required, children }) {
  const id = useId()
  const child = typeof children === 'function' ? children({ id, 'aria-describedby': hint || error ? id + '-d' : undefined }) : children
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-white/90">
        {label}{required && <span className="text-purple-300"> *</span>}
      </label>
      {child}
      {(hint || error) && (
        <p id={id + '-d'} className={`text-xs ${error ? 'text-red-300' : 'text-white/50'}`}>{error || hint}</p>
      )}
    </div>
  )
}

const TONES = {
  amber: 'bg-amber-500/15 text-amber-200 ring-amber-500/30',
  blue: 'bg-sky-500/15 text-sky-200 ring-sky-500/30',
  orange: 'bg-orange-500/15 text-orange-200 ring-orange-500/30',
  purple: 'bg-purple-500/20 text-purple-200 ring-purple-500/40',
  green: 'bg-emerald-500/15 text-emerald-200 ring-emerald-500/30',
  slate: 'bg-white/10 text-white/70 ring-white/15',
  red: 'bg-red-500/15 text-red-200 ring-red-500/30',
}

export function Badge({ tone = 'slate', children, title }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  )
}

export function StatusBadge({ status, isReporter = false }) {
  const { label, tone } = statusInfo(status, { isReporter })
  return <Badge tone={tone}>{label}</Badge>
}

/** Accessible modal: closes on Escape and the backdrop, focus moves in and returns. */
export function Modal({ open, title, onClose, children }) {
  const ref = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose            // always the latest, without re-running the effect below
  useEffect(() => {
    if (!open) return undefined
    const previous = document.activeElement
    ref.current?.focus()                 // only when the dialog opens, never again while typing
    const onKey = (e) => { if (e.key === 'Escape') closeRef.current() }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus?.() }
  }, [open])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 sm:items-center" onMouseDown={onClose}>
      <div
        ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-white/15 bg-[#1a0f2e] p-5 shadow-2xl focus:outline-none"
      >
        <h2 className="mb-3 text-lg font-semibold text-white">{title}</h2>
        {children}
      </div>
    </div>
  )
}
