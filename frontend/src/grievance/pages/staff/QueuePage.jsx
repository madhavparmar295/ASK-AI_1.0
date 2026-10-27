import { useState } from 'react'
import { ClipboardList } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { EmptyState, ErrorBox, Spinner, inputClass } from '../../components/ui'
import { TicketCard } from '../../components/TicketCard'
import { usePagedList } from '../../hooks/usePagedList'
import { STATUS_OPTIONS, statusInfo } from '../../lib/status'
import { Button } from '../../components/ui'

const TITLES = {
  mine: ['My queue', 'Tickets assigned to you, soonest deadline first.', 'Nothing is assigned to you right now.'],
  team: ['Team', 'Everything in your chain: your own tickets and those of the people you oversee.', 'No tickets in your chain.'],
  overdue: ['Overdue', 'Tickets in your chain that are past their deadline.', 'Nothing is overdue. Well done.'],
}

/** The three staff lists. mode: 'mine' | 'team' | 'overdue'. */
export default function QueuePage({ mode = 'mine' }) {
  const api = useApi()
  const [status, setStatus] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [title, subtitle, empty] = TITLES[mode]
  const list = usePagedList(
    (page) => (mode === 'overdue' ? api.staffOverdue(page) : api.staffIssues({ scope: mode, status, overdue: overdueOnly, ...page })),
    [mode, status, overdueOnly],
  )

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <p className="text-sm text-white/60">{subtitle}</p>
      </div>

      {mode !== 'overdue' && (
        <div className="flex flex-wrap items-center gap-3">
          <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className={`${inputClass} !w-auto`}>
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{statusInfo(s).label}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm text-white/80">
            <input type="checkbox" className="h-4 w-4 accent-purple-500" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} />
            Overdue only
          </label>
          <span className="ml-auto text-sm text-white/50">{list.loading ? '' : `${list.total} ticket${list.total === 1 ? '' : 's'}`}</span>
        </div>
      )}

      {list.loading ? <Spinner /> : list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : list.items.length === 0 ? (
        <EmptyState icon={ClipboardList} title={status || overdueOnly ? 'No tickets match these filters' : empty} />
      ) : (
        <>
          <ul className="space-y-3">{list.items.map((t) => <li key={t.id}><TicketCard ticket={t} staffView /></li>)}</ul>
          {list.hasMore && <div className="text-center"><Button variant="secondary" loading={list.loadingMore} onClick={list.loadMore}>Show more</Button></div>}
        </>
      )}
    </div>
  )
}
