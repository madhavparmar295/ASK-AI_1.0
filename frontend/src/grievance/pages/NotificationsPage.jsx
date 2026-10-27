import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useApi } from '../api/ApiContext'
import { Button, Card, EmptyState, ErrorBox, Spinner } from '../components/ui'
import { href } from '../config'
import { usePagedList } from '../hooks/usePagedList'
import { formatDateTime } from '../lib/format'

export default function NotificationsPage() {
  const api = useApi()
  const navigate = useNavigate()
  const list = usePagedList((page) => api.notifications(page), [])

  async function open(n) {
    if (!n.read) {
      api.markRead(n.id).catch(() => {})
      list.setItems((items) => items.map((x) => (x.id === n.id ? { ...x, read: true } : x)))
    }
    if (n.ticket_id) navigate(href(`issues/${n.ticket_id}`))
  }
  async function readAll() {
    await api.readAll().catch(() => {})
    list.setItems((items) => items.map((x) => ({ ...x, read: true })))
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Notifications</h2>
        <Button variant="secondary" className="ml-auto" onClick={readAll} disabled={!list.items.some((n) => !n.read)}>Mark all as read</Button>
      </div>
      {list.loading ? <Spinner /> : list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : list.items.length === 0 ? (
        <EmptyState icon={Bell} title="No notifications yet">You will see updates about your tickets here.</EmptyState>
      ) : (
        <>
          <ul className="space-y-2">
            {list.items.map((n) => (
              <li key={n.id}>
                <button onClick={() => open(n)} className="block w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 rounded-2xl">
                  <Card className={`transition hover:bg-white/10 ${n.read ? 'opacity-70' : 'border-purple-400/40'}`}>
                    <div className="flex items-start gap-3">
                      {!n.read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-purple-400" aria-label="Unread" />}
                      <div>
                        <p className="text-sm text-white">{n.text}</p>
                        <p className="text-xs text-white/50">{formatDateTime(n.created_at)}</p>
                      </div>
                    </div>
                  </Card>
                </button>
              </li>
            ))}
          </ul>
          {list.hasMore && <div className="text-center"><Button variant="secondary" loading={list.loadingMore} onClick={list.loadMore}>Show more</Button></div>}
        </>
      )}
    </div>
  )
}
