import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { NotFound } from '../../auth/guards'
import { href } from '../../config'
import AuditPage from './AuditPage'
import CategoriesPage from './CategoriesPage'
import DashboardPage from './DashboardPage'
import HealthPage from './HealthPage'
import LocationsPage from './LocationsPage'
import RoutingPage from './RoutingPage'
import TicketsPage from './TicketsPage'
import UsersPage from './UsersPage'

const TABS = [
  ['dashboard', 'Dashboard'], ['tickets', 'All tickets'], ['categories', 'Categories'], ['locations', 'Locations'],
  ['routing', 'Routing'], ['users', 'Users'], ['audit', 'Change log'], ['health', 'System health'],
]

export default function AdminRoutes() {
  return (
    <div className="space-y-4">
      <nav aria-label="Admin sections" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {TABS.map(([to, label]) => (
          <NavLink key={to} to={href(`admin/${to}`)}
            className={({ isActive }) => `whitespace-nowrap rounded-lg px-3 py-1 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 ${isActive ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/10'}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate replace to={href('admin/dashboard')} />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="locations" element={<LocationsPage />} />
        <Route path="routing" element={<RoutingPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  )
}
