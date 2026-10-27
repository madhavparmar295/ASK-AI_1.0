import { Link } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useApi } from '../api/ApiContext'
import { href } from '../config'
import { useAsync } from '../hooks/useAsync'
import { useInterval } from '../hooks/useInterval'

/** Bell with the unread count. Checks every minute while the tab is open. */
export default function NotificationBell() {
  const api = useApi()
  const { data, reload } = useAsync(() => api.unreadCount().catch(() => ({ unread: 0 })), [])
  useInterval(reload, 60000)
  const n = data?.unread || 0
  return (
    <Link to={href('notifications')} aria-label={n ? `Notifications, ${n} unread` : 'Notifications'}
      className="relative rounded-full p-2 text-white/80 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400">
      <Bell className="h-5 w-5" aria-hidden="true" />
      {n > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-purple-600 px-1 text-[10px] font-bold text-white">
          {n > 99 ? '99+' : n}
        </span>
      )}
    </Link>
  )
}
