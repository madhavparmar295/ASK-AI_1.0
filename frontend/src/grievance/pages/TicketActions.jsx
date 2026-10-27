import { useState } from 'react'
import { useApi } from '../api/ApiContext'
import { FilePicker } from '../components/FilePicker'
import { StarRating } from '../components/StarRating'
import { Alert, Button, Card, Field, Modal, inputClass } from '../components/ui'
import { useToast } from '../components/Toast'
import { useAsync } from '../hooks/useAsync'

// Actions that need some text first. The server decides which ones are allowed (ticket.actions).
const TEXT_ACTIONS = {
  reply: { button: 'Reply', title: 'Reply', label: 'Your message', required: true, submit: 'Send', done: 'Reply sent', call: (api, id, v) => api.reply(id, v) },
  reopen: { button: 'It is not fixed', title: 'Tell us what is still wrong', label: 'What is still wrong?', required: true, max: 500, submit: 'Reopen', done: 'The ticket was reopened', call: (api, id, v) => api.reopen(id, v) },
  request_info: { button: 'Ask for information', title: 'Ask the reporter', label: 'What do you need to know?', required: true, submit: 'Send question', done: 'Question sent. The deadline is paused until they reply', call: (api, id, v) => api.requestInfo(id, v) },
  resolve: { button: 'Mark as resolved', title: 'Resolve', label: 'What was done?', required: true, submit: 'Resolve', done: 'Marked as resolved', call: (api, id, v) => api.resolve(id, v) },
  escalate: { button: 'Escalate', title: 'Escalate to the next level', label: 'Why?', required: true, max: 500, submit: 'Escalate', done: 'Escalated to the next level', call: (api, id, v) => api.escalate(id, v) },
  cancel: { button: 'Cancel this ticket', title: 'Cancel this ticket?', label: 'Reason (optional)', required: false, max: 500, submit: 'Cancel ticket', done: 'The ticket was cancelled', danger: true, call: (api, id, v) => api.cancel(id, v) },
}
const DIRECT = {
  start: { button: 'Start work', done: 'Work started', call: (api, id) => api.start(id) },
  confirm: { button: 'Yes, it is fixed', done: 'Thank you. The ticket is closed', call: (api, id) => api.confirm(id) },
}
const ORDER = ['start', 'request_info', 'resolve', 'escalate', 'reassign', 'reply', 'confirm', 'reopen', 'feedback', 'upload', 'cancel']

/**
 * The buttons on a ticket. They come from ticket.actions (decided by the server), so this
 * file never works out permissions itself.
 */
export default function TicketActions({ ticket, onChange, onReload }) {
  const api = useApi()
  const toast = useToast()
  const [open, setOpen] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const actions = ORDER.filter((a) => ticket.actions.includes(a))
  if (actions.length === 0) return null

  async function run(call, done, closeOnSuccess = true) {
    setBusy(true); setError(null)
    try {
      const result = await call()
      toast(done)
      if (closeOnSuccess) setOpen(null)
      return result
    } catch (e) {
      setError(e)
      return undefined
    } finally { setBusy(false) }
  }

  async function runTicket(call, done) {            // the call returns the updated ticket
    const t = await run(call, done)
    if (t) onChange(t)
  }

  const buttonVariant = (a) => (a === 'cancel' ? 'ghost' : a === 'start' || a === 'resolve' || a === 'confirm' || a === 'reply' ? 'primary' : 'secondary')

  return (
    <Card className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">What would you like to do?</h2>
      <div className="flex flex-wrap gap-2">
        {actions.map((a) => (
          <Button key={a} variant={buttonVariant(a)} disabled={busy}
            onClick={() => {
              setError(null)
              if (DIRECT[a]) runTicket(() => DIRECT[a].call(api, ticket.id), DIRECT[a].done)
              else setOpen(open === a ? null : a)
            }}>
            {DIRECT[a]?.button || TEXT_ACTIONS[a]?.button || { reassign: 'Reassign', feedback: 'Give feedback', upload: 'Add a file' }[a]}
          </Button>
        ))}
      </div>

      {error && <Alert tone="error">{error.message}</Alert>}

      {open && TEXT_ACTIONS[open] && open !== 'cancel' && (
        <TextForm key={open} cfg={TEXT_ACTIONS[open]} busy={busy}
          onSubmit={(v) => runTicket(() => TEXT_ACTIONS[open].call(api, ticket.id, v), TEXT_ACTIONS[open].done)} onClose={() => setOpen(null)} />
      )}
      {open === 'cancel' && (
        <Modal open title={TEXT_ACTIONS.cancel.title} onClose={() => setOpen(null)}>
          <TextForm cfg={TEXT_ACTIONS.cancel} busy={busy} bare cancelLabel="Keep it"
            onSubmit={(v) => runTicket(() => TEXT_ACTIONS.cancel.call(api, ticket.id, v), TEXT_ACTIONS.cancel.done)} onClose={() => setOpen(null)} />
        </Modal>
      )}
      {open === 'reassign' && <ReassignForm ticketId={ticket.id} busy={busy} onClose={() => setOpen(null)}
        onSubmit={(assignee, reason) => runTicket(() => api.reassign(ticket.id, assignee, reason), 'Reassigned')} />}
      {open === 'feedback' && <FeedbackForm busy={busy} onClose={() => setOpen(null)}
        onSubmit={async (rating, comment) => { const r = await run(() => api.feedback(ticket.id, rating, comment), 'Thank you for your feedback'); if (r) onReload() }} />}
      {open === 'upload' && <UploadForm attached={ticket.attachments.filter((a) => a.uploaded_by_me).length} busy={busy} onClose={() => setOpen(null)}
        onSubmit={async (files) => {
          const failed = []
          setBusy(true); setError(null)
          for (const f of files) { try { await api.uploadAttachment(ticket.id, f) } catch (e) { failed.push(`${f.name}: ${e.message}`) } }
          setBusy(false)
          if (failed.length) setError(new Error(failed.join(' · '))); else { toast('File added'); setOpen(null) }
          onReload()
        }} />}
    </Card>
  )
}

function TextForm({ cfg, busy, onSubmit, onClose, bare = false, cancelLabel = 'Close' }) {
  const [value, setValue] = useState('')
  const [problem, setProblem] = useState('')
  function go(e) {
    e.preventDefault()
    const v = value.trim()
    if (cfg.required && !v) { setProblem('Please write something first.'); return }
    onSubmit(v)
  }
  return (
    <form onSubmit={go} className={bare ? 'space-y-3' : 'space-y-3 rounded-xl bg-white/5 p-3'} noValidate>
      <Field label={cfg.label} error={problem} required={cfg.required}>
        {(p) => <textarea {...p} rows={3} maxLength={cfg.max || 2000} value={value}
          onChange={(e) => { setValue(e.target.value); setProblem('') }} className={inputClass} />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>{cancelLabel}</Button>
        <Button type="submit" variant={cfg.danger ? 'danger' : 'primary'} loading={busy}>{cfg.submit}</Button>
      </div>
    </form>
  )
}

function ReassignForm({ ticketId, busy, onSubmit, onClose }) {
  const api = useApi()
  const people = useAsync(() => api.reassignOptions(ticketId), [ticketId])
  const [who, setWho] = useState('')
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState('')
  function go(e) {
    e.preventDefault()
    if (!who || !reason.trim()) { setProblem('Choose a person and write a reason.'); return }
    onSubmit(who, reason.trim())
  }
  return (
    <form onSubmit={go} className="space-y-3 rounded-xl bg-white/5 p-3" noValidate>
      {people.error && <Alert tone="error">{people.error.message}</Alert>}
      <Field label="Assign to" required>
        {(p) => (
          <select {...p} value={who} onChange={(e) => { setWho(e.target.value); setProblem('') }} className={inputClass} disabled={people.loading}>
            <option value="">{people.loading ? 'Loading…' : 'Choose a person…'}</option>
            {(people.data || []).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.role})</option>)}
          </select>
        )}
      </Field>
      <Field label="Reason" required error={problem}>
        {(p) => <textarea {...p} rows={2} maxLength={500} value={reason} onChange={(e) => { setReason(e.target.value); setProblem('') }} className={inputClass} />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button type="submit" loading={busy}>Reassign</Button>
      </div>
    </form>
  )
}

function FeedbackForm({ busy, onSubmit, onClose }) {
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')
  const [problem, setProblem] = useState('')
  function go(e) {
    e.preventDefault()
    if (!rating) { setProblem('Please choose a rating.'); return }
    onSubmit(rating, comment.trim())
  }
  return (
    <form onSubmit={go} className="space-y-3 rounded-xl bg-white/5 p-3" noValidate>
      <p className="text-sm text-white/90">How was it handled?</p>
      <StarRating value={rating} onChange={(n) => { setRating(n); setProblem('') }} />
      {problem && <p className="text-xs text-red-300">{problem}</p>}
      <Field label="Anything to add? (optional)">
        {(p) => <textarea {...p} rows={2} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} className={inputClass} />}
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button type="submit" loading={busy}>Send feedback</Button>
      </div>
    </form>
  )
}

function UploadForm({ attached, busy, onSubmit, onClose }) {
  const [files, setFiles] = useState([])
  const [errors, setErrors] = useState([])
  return (
    <div className="space-y-3 rounded-xl bg-white/5 p-3">
      <FilePicker files={files} onChange={setFiles} alreadyAttached={attached} errors={errors} onErrors={setErrors} />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button loading={busy} disabled={files.length === 0} onClick={() => onSubmit(files)}>Upload</Button>
      </div>
    </div>
  )
}
