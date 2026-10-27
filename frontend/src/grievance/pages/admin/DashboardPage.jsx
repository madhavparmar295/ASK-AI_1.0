import { Link } from 'react-router-dom'
import { useApi } from '../../api/ApiContext'
import { Card, ErrorBox, Spinner } from '../../components/ui'
import { href } from '../../config'
import { useAsync } from '../../hooks/useAsync'
import { statusInfo } from '../../lib/status'

function Stat({ label, value, tone = 'text-white', to }) {
  const body = (
    <Card className="h-full">
      <p className="text-xs uppercase tracking-wide text-white/50">{label}</p>
      <p className={`mt-1 text-3xl font-semibold ${tone}`}>{value}</p>
    </Card>
  )
  return to ? <Link to={to} className="block rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400">{body}</Link> : body
}

export default function DashboardPage() {
  const api = useApi()
  const { data, error, loading, reload } = useAsync(() => api.adminStats(), [])
  if (loading && !data) return <Spinner />
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />
  const { tickets, by_category: cats, feedback, emails_waiting: waiting } = data
  const max = Math.max(1, ...Object.values(tickets.by_status))

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Open tickets" value={tickets.open} />
        <Stat label="Overdue" value={tickets.overdue} tone={tickets.overdue ? 'text-red-300' : 'text-white'} to={href('admin/tickets?overdue=true')} />
        <Stat label="Reported, last 7 days" value={tickets.created_last_7_days} />
        <Stat label="Closed, last 7 days" value={tickets.closed_last_7_days} />
        <Stat label="All tickets" value={tickets.total} />
        <Stat label="Average rating" value={feedback.average === null ? '–' : `${feedback.average} / 5`} />
        <Stat label="Feedback received" value={feedback.count} />
        <Stat label="Emails waiting" value={waiting} tone={waiting > 20 ? 'text-amber-300' : 'text-white'} to={href('admin/health')} />
      </div>

      <Card className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">By status</h2>
        {Object.entries(tickets.by_status).map(([s, n]) => (
          <div key={s} className="flex items-center gap-3 text-sm">
            <span className="w-40 shrink-0 text-white/80">{statusInfo(s).label}</span>
            <div className="h-3 flex-1 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-purple-500" style={{ width: `${(n / max) * 100}%` }} /></div>
            <span className="w-8 text-right tabular-nums text-white/80">{n}</span>
          </div>
        ))}
      </Card>

      <Card className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/60">By category</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-left text-sm text-white/90">
            <thead className="text-xs uppercase text-white/50"><tr><th className="py-1">Category</th><th>All</th><th>Open</th><th>Overdue</th></tr></thead>
            <tbody>
              {cats.map((c) => (
                <tr key={c.category_id} className="border-t border-white/5">
                  <td className="py-1.5">{c.category}{c.confidential && <span className="ml-2 text-xs text-purple-300">(confidential: counted only)</span>}</td>
                  <td>{c.total}</td><td>{c.open}</td><td className={c.overdue ? 'text-red-300' : ''}>{c.overdue}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-white/50">Confidential tickets are counted here but never listed, and administrators cannot open them.</p>
      </Card>
    </div>
  )
}
