import { NavLink } from 'react-router-dom'
import { ArrowLeft, LogOut } from 'lucide-react'
import { useAuth, isStaff } from '../auth/AuthContext'
import { href } from '../config'
import NotificationBell from './NotificationBell'

/** Menu entries for the signed-in person. Exported so tests and the shell can reuse it. */
export function navItems(me) {
  if (!me) return []
  const items = []
  if (isStaff(me)) items.push({ to: 'queue', label: 'My queue' })
  if (isStaff(me) && (me.is_head || me.role === 'officer')) {
    items.push({ to: 'team', label: 'Team' }, { to: 'overdue', label: 'Overdue' })
  }
  items.push({ to: 'issues', label: 'My issues' }, { to: 'new', label: 'Report a problem' })
  if (me.role === 'admin') items.push({ to: 'admin', label: 'Admin' })
  return items
}

/**
 * The frame around every grievance page.
 * THIS is the only part that depends on the chatbot's shell: if the shell already has a header,
 * keep just the <nav> and the <main> and drop the rest.
 */
export default function GrievanceLayout({ children }) {
  const { me, logout } = useAuth()
  const items = navItems(me)
  return (
    <div className="grievance-surface mx-auto w-full max-w-5xl space-y-5 px-3 py-4 sm:px-6" style={{ colorScheme: 'dark' }}>
      <header className="flex items-center gap-3">
        {/* The chat shell is not rendered on these pages, so the way back is explicit. */}
        <a
          href="/"
          className="flex items-center gap-1 rounded-full bg-white/5 px-3 py-1.5 text-sm text-white/70 transition hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Chat
        </a>
        <h1 className="text-lg font-semibold text-white sm:text-xl">Grievance system</h1>
        <div className="ml-auto flex items-center gap-1">
          {me && <NotificationBell />}
          {me && (
            <>
              <span className="hidden max-w-[10rem] truncate text-sm text-white/70 sm:inline" title={me.email}>{me.name}</span>
              <button onClick={logout} aria-label="Sign out"
                className="rounded-full p-2 text-white/80 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400">
                <LogOut className="h-5 w-5" aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </header>

      {items.length > 0 && (
        <nav aria-label="Grievance sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
          {items.map((i) => (
            <NavLink key={i.to} to={href(i.to)}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 ${
                  isActive ? 'bg-purple-600 text-white' : 'bg-white/5 text-white/70 hover:bg-white/10'}`}>
              {i.label}
            </NavLink>
          ))}
        </nav>
      )}
      <main>{children}</main>
    </div>
  )
}
