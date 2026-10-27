import { Link } from 'react-router-dom'
import { AlertTriangle, ChevronRight, Clock, ShieldAlert } from 'lucide-react'
import { href } from '../config'
import { formatDateTime, timeUntil } from '../lib/format'
import { Badge, Card, StatusBadge } from './ui'

/** One row in any list of tickets (student list, staff queue, overdue). */
export function TicketCard({ ticket, staffView = false }) {
  const due = staffView || ticket.status === 'ASSIGNED' ? timeUntil(ticket.due_at) : { text: '', overdue: false }
  const showDue = ticket.due_at && ['ASSIGNED', 'IN_PROGRESS', 'ESCALATED'].includes(ticket.status)
  return (
    <Link to={href(`issues/${ticket.id}`)} className="group block focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 rounded-2xl">
      <Card className="transition group-hover:border-purple-400/40 group-hover:bg-white/10">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold tracking-wide text-purple-300">{ticket.ticket_no}</span>
              <StatusBadge status={ticket.status} isReporter={!staffView} />
              {ticket.urgent && <Badge tone="red"><AlertTriangle className="h-3 w-3" aria-hidden="true" /> Urgent</Badge>}
              {ticket.confidential && <Badge tone="purple"><ShieldAlert className="h-3 w-3" aria-hidden="true" /> Confidential</Badge>}
              {ticket.escalation_level > 0 && <Badge tone="orange">Level {ticket.escalation_level}</Badge>}
            </div>
            <p className="line-clamp-2 text-sm text-white">{ticket.title}</p>
            <p className="text-xs text-white/50">
              {ticket.category.name}{ticket.unit ? ` · ${ticket.unit.name}` : ''}
              {staffView && ticket.reporter_name ? ` · from ${ticket.reporter_name}` : ''}
              {!staffView && ticket.assignee ? ` · with ${ticket.assignee.name}` : ''}
              {' · '}{formatDateTime(ticket.created_at)}
            </p>
            {showDue && (
              <p className={`flex items-center gap-1 text-xs ${due.overdue || ticket.overdue ? 'font-medium text-red-300' : 'text-white/60'}`}>
                <Clock className="h-3 w-3" aria-hidden="true" /> {due.text}
              </p>
            )}
          </div>
          <ChevronRight className="mt-1 h-5 w-5 text-white/30 group-hover:text-purple-300" aria-hidden="true" />
        </div>
      </Card>
    </Link>
  )
}
