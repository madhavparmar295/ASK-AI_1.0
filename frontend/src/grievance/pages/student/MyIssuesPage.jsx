import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Inbox, Plus } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { Button, EmptyState, ErrorBox, Spinner, inputClass } from '../../components/ui'
import { TicketCard } from '../../components/TicketCard'
import { href } from '../../config'
import { usePagedList } from '../../hooks/usePagedList'
import { STATUS_OPTIONS, statusInfo } from '../../lib/status'

export default function MyIssuesPage() {
  const api = useApi()
  const [status, setStatus] = useState('')
  const list = usePagedList((page) => api.myIssues({ status, ...page }), [status])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">My issues</h2>
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className={`${inputClass} ml-auto !w-auto`}>
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{statusInfo(s, { isReporter: true }).label}</option>)}
        </select>
        <Link to={href('new')}><Button><Plus className="h-4 w-4" aria-hidden="true" /> Report a problem</Button></Link>
      </div>

      {list.loading ? <Spinner /> : list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : list.items.length === 0 ? (
        <EmptyState icon={Inbox} title={status ? 'No issues with this status' : 'You have not reported anything yet'}>
          {status ? 'Try another status.' : 'When something is wrong on campus, report it here and follow what happens.'}
        </EmptyState>
      ) : (
        <>
          <ul className="space-y-3">{list.items.map((t) => <li key={t.id}><TicketCard ticket={t} /></li>)}</ul>
          {list.hasMore && <div className="text-center"><Button variant="secondary" loading={list.loadingMore} onClick={list.loadMore}>Show more</Button></div>}
        </>
      )}
    </div>
  )
}
