import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { vi } from 'vitest'
import { GrievanceRoutes } from '../grievance/GrievanceApp'
import { ApiError } from '../grievance/api/client'

export const ME = {
  student: { id: 'u-ravi', name: 'Ravi Kumar', email: 'ravi@college.edu', role: 'student', department: 'CSE', hostel: 'Hostel A', room: 'A-101', is_head: false },
  staff: { id: 'u-care', name: 'Caretaker Hostel A', email: 'caretaker_a@college.edu', role: 'staff', department: null, hostel: null, room: null, is_head: false },
  head: { id: 'u-ward', name: 'Warden', email: 'warden@college.edu', role: 'staff', department: null, hostel: null, room: null, is_head: true },
  officer: { id: 'u-off', name: 'Designated Officer 1', email: 'officer1@college.edu', role: 'officer', department: null, hostel: null, room: null, is_head: true },
  admin: { id: 'u-adm', name: 'Admin Office', email: 'admin@college.edu', role: 'admin', department: null, hostel: null, room: null, is_head: false },
}

export const OPTIONS = {
  categories: [
    { id: 'c-host', name: 'Hostel and housing', unit_type: 'hostel', confidential: false },
    { id: 'c-lib', name: 'Library', unit_type: 'campus', confidential: false },
    { id: 'c-conf', name: 'Harassment, ragging, discrimination, safety', unit_type: 'campus', confidential: true },
    { id: 'c-other', name: 'Other', unit_type: 'campus', confidential: false },
  ],
  units: [
    { id: 'u-ha', type: 'hostel', name: 'Hostel A' },
    { id: 'u-hb', type: 'hostel', name: 'Hostel B' },
  ],
}

export function listItem(over = {}) {
  return {
    id: 't1', ticket_no: 'GRV-2026-000001', status: 'ASSIGNED', title: 'The AC in my room is not working',
    category: { id: 'c-host', name: 'Hostel and housing' }, unit: { id: 'u-ha', name: 'Hostel A' },
    assignee: { id: 'u-care', name: 'Caretaker Hostel A' }, reporter_name: null, escalation_level: 0,
    due_at: new Date(Date.now() + 5 * 3600e3).toISOString(), overdue: false, confidential: false, urgent: false,
    created_at: '2026-10-08T10:00:00Z', ...over,
  }
}

export function ticket(over = {}) {
  return {
    id: 't1', ticket_no: 'GRV-2026-000001', status: 'ASSIGNED',
    category: { id: 'c-host', name: 'Hostel and housing' }, unit: { id: 'u-ha', name: 'Hostel A' },
    location_text: 'A-101', description: 'The AC in my room is not working', confidential: false, urgent: false,
    escalation_level: 0, due_at: new Date(Date.now() + 5 * 3600e3).toISOString(), overdue: false,
    assignee: { id: 'u-care', name: 'Caretaker Hostel A' }, reporter: null,
    created_at: '2026-10-08T10:00:00Z', updated_at: '2026-10-08T10:00:00Z', resolved_at: null, closed_at: null,
    attachments: [], events: [{ type: 'status', from_status: null, to_status: 'ASSIGNED', text: 'Ticket created', actor: 'You', created_at: '2026-10-08T10:00:00Z', internal: null }],
    actions: [], feedback: null, ...over,
  }
}

export const REPORTER_INFO = { id: 'u-ravi', name: 'Ravi Kumar', email: 'ravi@college.edu', department: 'CSE', hostel: 'Hostel A', room: 'A-101' }
export const page = (items, total = items.length) => ({ items, total, limit: 20, offset: 0 })

export const STATS = {
  tickets: { total: 40, open: 12, overdue: 3, created_last_7_days: 9, closed_last_7_days: 7,
    by_status: { ASSIGNED: 5, IN_PROGRESS: 4, ESCALATED: 1, NEEDS_INFO: 2, RESOLVED: 3, CLOSED: 24, CANCELLED: 1 } },
  by_category: [
    { category_id: 'c-host', category: 'Hostel and housing', confidential: false, total: 20, open: 6, overdue: 2 },
    { category_id: 'c-conf', category: 'Harassment, ragging, discrimination, safety', confidential: true, total: 2, open: 1, overdue: 0 },
  ],
  feedback: { count: 15, average: 4.2 }, emails_waiting: 4,
}
export const CATEGORIES = [
  { id: 'c-host', name: 'Hostel and housing', confidential: false, sla_hours: 24, unit_type: 'hostel', keywords: 'hostel:3, ac', active: true },
  { id: 'c-lib', name: 'Library', confidential: false, sla_hours: 72, unit_type: 'campus', keywords: null, active: true },
  { id: 'c-conf', name: 'Harassment, ragging, discrimination, safety', confidential: true, sla_hours: 24, unit_type: 'campus', keywords: null, active: true },
]
export const UNITS = [
  { id: 'u-ha', type: 'hostel', name: 'Hostel A', active: true, routes: 1 },
  { id: 'u-hb', type: 'hostel', name: 'Hostel B', active: true, routes: 0 },
]
const person = (id, name, role = 'staff', active = true) => ({ id, name, email: `${id}@college.edu`, role, active })
export const USERS = [
  { ...person('u-care', 'Caretaker Hostel A'), department: null, hostel: null, room: null, created_at: '2026-01-01T00:00:00Z', in_routes: 1, warnings: [] },
  { ...person('u-ward', 'Warden'), department: null, hostel: null, room: null, created_at: '2026-01-01T00:00:00Z', in_routes: 3, warnings: [] },
  { ...person('u-off', 'Designated Officer 1', 'officer'), department: null, hostel: null, room: null, created_at: '2026-01-01T00:00:00Z', in_routes: 1, warnings: [] },
  { ...person('u-ravi', 'Ravi Kumar', 'student'), department: 'CSE', hostel: 'Hostel A', room: 'A-101', created_at: '2026-01-01T00:00:00Z', in_routes: 0, warnings: [] },
]
export const ROUTES = [
  { id: 'r1', category: { id: 'c-host', name: 'Hostel and housing' }, unit: { id: 'u-ha', name: 'Hostel A' },
    level0: person('u-care', 'Caretaker Hostel A'), level1: person('u-ward', 'Warden'), level2: null },
  { id: 'r2', category: { id: 'c-host', name: 'Hostel and housing' }, unit: null,
    level0: person('u-ward', 'Warden'), level1: null, level2: null },
]
export const HEALTH = {
  worker: { status: 'ok', last_heartbeat: '2026-10-08T10:00:00Z', minutes_ago: 1, last_run: { escalated: 0, auto_closed: 1, emails: { sent: 3, failed: 0 } }, last_error: null },
  email: { configured: true, waiting: 0, gave_up: 0, recent_failures: [] },
  overdue_tickets: 0,
  checks: { database: 'ok', uploads_dir_writable: true, clamav_enabled: true, dev_login_enabled: false, watchdog_enabled: true },
}

/** A fake API where every call is a vi.fn() that succeeds with a sensible default. */
export function fakeApi(over = {}) {
  const api = {
    client: { setOnUnauthorized: vi.fn(), setCsrf: vi.fn() },
    attachmentUrl: (id) => `/api/grievance/attachments/${id}`,
    me: vi.fn().mockResolvedValue(ME.student),
    devUsers: vi.fn().mockRejectedValue(new ApiError(404, 'Not found')),
    devLogin: vi.fn().mockResolvedValue(ME.student),
    googleLogin: vi.fn().mockResolvedValue(ME.student),
    logout: vi.fn().mockResolvedValue({ ok: true }),
    formOptions: vi.fn().mockResolvedValue(OPTIONS),
    classify: vi.fn().mockResolvedValue({ suggested: null, confidence: 'none', alternatives: [], confidential: false, urgent: false }),
    createIssue: vi.fn().mockResolvedValue(ticket()),
    myIssues: vi.fn().mockResolvedValue(page([])),
    getIssue: vi.fn().mockResolvedValue(ticket()),
    uploadAttachment: vi.fn().mockResolvedValue({ id: 'a1' }),
    reply: vi.fn(), cancel: vi.fn(), confirm: vi.fn(), reopen: vi.fn(), feedback: vi.fn().mockResolvedValue({ rating: 5 }),
    staffIssues: vi.fn().mockResolvedValue(page([])), staffOverdue: vi.fn().mockResolvedValue(page([])),
    start: vi.fn(), requestInfo: vi.fn(), resolve: vi.fn(), escalate: vi.fn(), reassign: vi.fn(),
    reassignOptions: vi.fn().mockResolvedValue([{ id: 'u-cb', name: 'Caretaker Hostel B', role: 'staff' }]),
    adminStats: vi.fn().mockResolvedValue(STATS),
    adminIssues: vi.fn().mockResolvedValue(page([])),
    adminCategories: vi.fn().mockResolvedValue(CATEGORIES),
    adminCreateCategory: vi.fn().mockResolvedValue({}), adminUpdateCategory: vi.fn().mockResolvedValue({}),
    adminUnits: vi.fn().mockResolvedValue(UNITS),
    adminCreateUnit: vi.fn().mockResolvedValue({}), adminUpdateUnit: vi.fn().mockResolvedValue({}),
    adminRouting: vi.fn().mockResolvedValue({ items: ROUTES, total: ROUTES.length }),
    adminCreateRoute: vi.fn().mockResolvedValue({}), adminUpdateRoute: vi.fn().mockResolvedValue({}), adminDeleteRoute: vi.fn().mockResolvedValue(null),
    adminUsers: vi.fn().mockImplementation(async ({ role } = {}) => {
      const items = USERS.filter((u) => !role || u.role === role)
      return { items, total: items.length }
    }),
    adminCreateUser: vi.fn().mockResolvedValue({}), adminUpdateUser: vi.fn().mockResolvedValue({ warnings: [] }),
    adminTemplate: vi.fn().mockResolvedValue('a,b\n1,2\n'),
    adminImport: vi.fn().mockResolvedValue({ dry_run: true, created: 0, updated: 0, errors: 0, rows: [] }),
    adminAudit: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    adminHealth: vi.fn().mockResolvedValue(HEALTH),
    notifications: vi.fn().mockResolvedValue({ items: [], total: 0, unread: 0 }),
    unreadCount: vi.fn().mockResolvedValue({ unread: 0 }),
    markRead: vi.fn().mockResolvedValue({}), readAll: vi.fn().mockResolvedValue({ ok: true }),
  }
  return Object.assign(api, over)
}

function Where() {
  const l = useLocation()
  return <div data-testid="where">{l.pathname}{l.search}</div>
}

/** Render the whole grievance module at a URL, like the browser would. */
export function renderAt(path, api = fakeApi()) {
  const user = userEvent.setup()
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/grievance/*" element={<><GrievanceRoutes api={api} /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  )
  return { user, api, ...view }
}
