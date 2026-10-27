import { Link, useLocation, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Clock, Download, FileText, Image as ImageIcon, ShieldAlert } from 'lucide-react'
import { useApi } from '../api/ApiContext'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, Card, ErrorBox, Spinner, StatusBadge } from '../components/ui'
import { Timeline } from '../components/Timeline'
import { href } from '../config'
import { useAsync } from '../hooks/useAsync'
import { formatDateTime, timeUntil } from '../lib/format'
import { sizeLabel } from '../lib/files'
import TicketActions from './TicketActions'

/** One ticket. The same page serves the reporter, the handler, heads and officers. */
export default function TicketPage() {
  const { id } = useParams()
  const api = useApi()
  const location = useLocation()
  const { me } = useAuth()
  const { data: ticket, error, loading, reload, setData } = useAsync(() => api.getIssue(id), [id])

  if (loading && !ticket) return <Spinner />
  if (error && !ticket) {
    return (
      <div className="space-y-3">
        <ErrorBox error={error.status === 404 ? new Error('This ticket was not found, or you do not have access to it.') : error}
          onRetry={error.status === 404 ? undefined : reload} />
        <Link to={href()} className="text-sm text-purple-300 underline">Back</Link>
      </div>
    )
  }

  const isReporter = ticket.reporter === null          // the server hides the reporter from themselves
  const due = ticket.due_at && ['ASSIGNED', 'IN_PROGRESS', 'ESCALATED'].includes(ticket.status) ? timeUntil(ticket.due_at) : null
  const failures = location.state?.uploadFailures || []

  return (
    <div className="space-y-4">
      <Link to={isReporter ? href('issues') : me?.role === 'admin' ? href('admin/tickets') : href('queue')} className="inline-flex items-center gap-1 text-sm text-white/60 hover:text-white">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back
      </Link>

      {location.state?.created && (
        <Alert tone="success" title="Your problem was received">
          Your ticket number is <strong>{ticket.ticket_no}</strong>. You will get a notification when something changes.
        </Alert>
      )}
      {failures.length > 0 && (
        <Alert tone="warn" title="Some files could not be added">
          <ul className="list-disc pl-4">{failures.map((f) => <li key={f}>{f}</li>)}</ul>
          <p className="mt-1">The ticket itself was created. You can add the files again below.</p>
        </Alert>
      )}
      {error && <ErrorBox error={error} onRetry={reload} />}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold tracking-wide text-purple-300">{ticket.ticket_no}</span>
          <StatusBadge status={ticket.status} isReporter={isReporter} />
          {ticket.urgent && <Badge tone="red"><AlertTriangle className="h-3 w-3" aria-hidden="true" /> Urgent</Badge>}
          {ticket.confidential && <Badge tone="purple"><ShieldAlert className="h-3 w-3" aria-hidden="true" /> Confidential</Badge>}
          {ticket.escalation_level > 0 && <Badge tone="orange">Escalated to level {ticket.escalation_level}</Badge>}
        </div>
        <p className="whitespace-pre-wrap break-words text-white">{ticket.description}</p>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <Row label="Category" value={ticket.category.name} />
          {ticket.unit && <Row label="Location" value={ticket.unit.name} />}
          {ticket.location_text && <Row label="Spot" value={ticket.location_text} />}
          <Row label="Reported" value={formatDateTime(ticket.created_at)} />
          {ticket.assignee && <Row label="Handled by" value={ticket.assignee.name} />}
          {ticket.resolved_at && <Row label="Resolved" value={formatDateTime(ticket.resolved_at)} />}
        </dl>
        {due && (
          <p className={`flex items-center gap-1 text-sm ${due.overdue ? 'font-medium text-red-300' : 'text-white/70'}`}>
            <Clock className="h-4 w-4" aria-hidden="true" /> {due.text}
          </p>
        )}
        {ticket.confidential && isReporter && (
          <p className="text-xs text-white/60">This ticket is confidential. Only designated officers can see it, and updates will not show details.</p>
        )}
      </Card>

      {ticket.reporter && (
        <Card className="space-y-1 text-sm">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">Reported by</h2>
          <p className="text-white">{ticket.reporter.name} <span className="text-white/50">({ticket.reporter.email})</span></p>
          <p className="text-white/70">
            {[ticket.reporter.department, ticket.reporter.hostel, ticket.reporter.room].filter(Boolean).join(' · ') || 'No location details on file'}
          </p>
        </Card>
      )}

      {ticket.attachments.length > 0 && (
        <Card className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">Files</h2>
          <ul className="space-y-1">
            {ticket.attachments.map((a) => (
              <li key={a.id}>
                <a href={api.attachmentUrl(a.id)} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10">
                  {a.mime_type === 'application/pdf' ? <FileText className="h-4 w-4" aria-hidden="true" /> : <ImageIcon className="h-4 w-4" aria-hidden="true" />}
                  <span className="min-w-0 flex-1 truncate">{a.original_name}</span>
                  <span className="text-xs text-white/50">{sizeLabel(a.size_bytes)}</span>
                  <Download className="h-4 w-4 text-white/60" aria-label="Download" />
                </a>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <TicketActions ticket={ticket} onChange={setData} onReload={reload} />

      <Card className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">History</h2>
        <Timeline events={ticket.events} />
        {ticket.feedback && <p className="text-sm text-white/70">Feedback given: {ticket.feedback.rating}/5{ticket.feedback.comment ? ` · ${ticket.feedback.comment}` : ''}</p>}
      </Card>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex gap-2">
      <dt className="text-white/50">{label}:</dt>
      <dd className="min-w-0 break-words text-white/90">{value}</dd>
    </div>
  )
}
