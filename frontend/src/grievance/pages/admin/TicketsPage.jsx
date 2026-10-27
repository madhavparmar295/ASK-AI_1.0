import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ClipboardList } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { Button, EmptyState, ErrorBox, Spinner, inputClass } from '../../components/ui'
import { TicketCard } from '../../components/TicketCard'
import { useAsync } from '../../hooks/useAsync'
import { useDebounce } from '../../hooks/useDebounce'
import { usePagedList } from '../../hooks/usePagedList'
import { STATUS_OPTIONS, statusInfo } from '../../lib/status'

/** Every ticket an admin may see. Confidential tickets never appear (the server leaves them out). */
export default function TicketsPage() {
  const api = useApi()
  const [params] = useSearchParams()
  const [status, setStatus] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [overdue, setOverdue] = useState(params.get('overdue') === 'true')
  const [q, setQ] = useState('')
  const search = useDebounce(q.trim(), 500)
  const cats = useAsync(() => api.adminCategories(), [])
  const list = usePagedList((page) => api.adminIssues({ status, categoryId, overdue, q: search, ...page }), [status, categoryId, overdue, search])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label="Search tickets" placeholder="Search number or words" value={q} onChange={(e) => setQ(e.target.value)} className={`${inputClass} !w-56`} />
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className={`${inputClass} !w-auto`}>
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{statusInfo(s).label}</option>)}
        </select>
        <select aria-label="Filter by category" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} className={`${inputClass} !w-auto`}>
          <option value="">All categories</option>
          {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm text-white/80">
          <input type="checkbox" className="h-4 w-4 accent-purple-500" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /> Overdue only
        </label>
        <span className="ml-auto text-sm text-white/50">{list.loading ? '' : `${list.total} ticket${list.total === 1 ? '' : 's'}`}</span>
      </div>
      {list.loading ? <Spinner /> : list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : list.items.length === 0 ? (
        <EmptyState icon={ClipboardList} title="No tickets match" />
      ) : (
        <>
          <ul className="space-y-3">{list.items.map((t) => <li key={t.id}><TicketCard ticket={t} staffView /></li>)}</ul>
          {list.hasMore && <div className="text-center"><Button variant="secondary" loading={list.loadingMore} onClick={list.loadMore}>Show more</Button></div>}
        </>
      )}
    </div>
  )
}
