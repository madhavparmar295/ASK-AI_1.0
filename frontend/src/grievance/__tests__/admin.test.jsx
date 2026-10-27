import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { HEALTH, ME, ROUTES, STATS, USERS, fakeApi, listItem, page, renderAt } from '../../test/helpers'

const admin = (over = {}) => fakeApi({ me: vi.fn().mockResolvedValue(ME.admin), ...over })
const csv = (name = 'data.csv') => new File(['a,b\n1,2\n'], name, { type: 'text/csv' })
const result = (over = {}) => ({ dry_run: true, created: 1, updated: 1, errors: 1, rows: [
  { row: 2, action: 'create', message: '' }, { row: 3, action: 'update', message: '' }, { row: 4, action: 'error', message: 'Unknown category "Nonsense"' }], ...over })

describe('admin area', () => {
  it('has a menu of sections and opens the dashboard first', async () => {
    renderAt('/grievance/admin', admin())
    expect(await screen.findByText('Open tickets')).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: /admin sections/i })
    expect(nav).toHaveTextContent(/Dashboard.*All tickets.*Categories.*Locations.*Routing.*Users.*Change log.*System health/)
    expect(screen.getByTestId('where')).toHaveTextContent('/grievance/admin/dashboard')
  })

  it('shows unknown admin addresses as not found', async () => {
    renderAt('/grievance/admin/nowhere', admin())
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })
})

describe('dashboard', () => {
  it('shows the numbers and says confidential tickets are only counted', async () => {
    renderAt('/grievance/admin/dashboard', admin())
    expect(await screen.findByText('Open tickets')).toBeInTheDocument()
    const stat = (label) => screen.getAllByText(label)[0].parentElement
    expect(stat('Open tickets')).toHaveTextContent('12')
    expect(stat('Overdue')).toHaveTextContent('3')
    expect(stat('Average rating')).toHaveTextContent('4.2 / 5')
    expect(screen.getByText(/confidential: counted only/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /overdue/i })).toHaveAttribute('href', '/grievance/admin/tickets?overdue=true')
  })

  it('handles no feedback yet and a failing server', async () => {
    const api = admin({ adminStats: vi.fn().mockResolvedValue({ ...STATS, feedback: { count: 0, average: null } }) })
    renderAt('/grievance/admin/dashboard', api)
    expect(await screen.findByText('Average rating')).toBeInTheDocument()
    expect(screen.getByText('Average rating').parentElement).toHaveTextContent('–')
    renderAt('/grievance/admin/dashboard', admin({ adminStats: vi.fn().mockRejectedValue(new ApiError(500, 'x')) }))
    expect(await screen.findByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})

describe('all tickets', () => {
  it('filters and searches, and starts from the overdue link', async () => {
    const api = admin({ adminIssues: vi.fn().mockResolvedValue(page([listItem({ reporter_name: 'Ravi Kumar' })])) })
    const { user } = renderAt('/grievance/admin/tickets?overdue=true', api)
    await screen.findByText('GRV-2026-000001')
    expect(api.adminIssues).toHaveBeenCalledWith(expect.objectContaining({ overdue: true }))
    await user.selectOptions(screen.getByLabelText(/filter by status/i), 'CLOSED')
    await waitFor(() => expect(api.adminIssues).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'CLOSED' })))
    await user.selectOptions(screen.getByLabelText(/filter by category/i), 'c-lib')
    await waitFor(() => expect(api.adminIssues).toHaveBeenLastCalledWith(expect.objectContaining({ categoryId: 'c-lib' })))
    await user.type(screen.getByLabelText(/search tickets/i), 'AC')
    await waitFor(() => expect(api.adminIssues).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'AC' })), { timeout: 2000 })
  })

  it('opening a ticket from here brings the admin back to this list', async () => {
    const { ticket } = await import('../../test/helpers')
    const api = admin({ getIssue: vi.fn().mockResolvedValue(ticket({ reporter: { id: 'x', name: 'Ravi', email: 'r@c.edu', department: null, hostel: null, room: null }, actions: ['escalate'] })) })
    renderAt('/grievance/issues/t1', api)
    expect(await screen.findByRole('link', { name: /back/i })).toHaveAttribute('href', '/grievance/admin/tickets')
  })
})

describe('categories', () => {
  it('lists them and adds one', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/categories', api)
    expect(await screen.findByText('Hostel and housing')).toBeInTheDocument()
    expect(screen.getAllByText('Confidential').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: /add a category/i }))
    await user.type(screen.getByLabelText(/^name/i), 'Sports')
    await user.clear(screen.getByLabelText(/deadline in hours/i))
    await user.type(screen.getByLabelText(/deadline in hours/i), '48')
    await user.selectOptions(screen.getByLabelText(/which location/i), 'building')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminCreateCategory).toHaveBeenCalledWith({ name: 'Sports', confidential: false, sla_hours: 48, unit_type: 'building', keywords: '', active: true })
    expect(await screen.findByText('Category added')).toBeInTheDocument()
  })

  it('edits keywords and the deadline', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/categories', api)
    await user.click(await screen.findByRole('button', { name: 'Edit Library' }))
    await user.type(screen.getByLabelText(/words that suggest/i), 'books, borrow*')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminUpdateCategory).toHaveBeenCalledWith('c-lib', expect.objectContaining({ keywords: 'books, borrow*', sla_hours: 72 }))
  })

  it('shows the server\'s refusal inside the form and keeps it open', async () => {
    const api = admin({ adminUpdateCategory: vi.fn().mockRejectedValue(new ApiError(409, 'At least one active confidential category with a default route must remain')) })
    const { user } = renderAt('/grievance/admin/categories', api)
    await user.click(await screen.findByRole('button', { name: /Edit Harassment/ }))
    await user.click(screen.getByLabelText(/^Active/))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one active confidential category/i)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('checks the form before sending', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/categories', api)
    await user.click(await screen.findByRole('button', { name: /add a category/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/please enter a name/i)).toBeInTheDocument()
    expect(api.adminCreateCategory).not.toHaveBeenCalled()
  })
})

describe('locations', () => {
  it('adds and edits', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/locations', api)
    expect(await screen.findByText('Hostel A')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /add a location/i }))
    await user.type(screen.getByLabelText(/^name/i), 'Hostel C')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminCreateUnit).toHaveBeenCalledWith({ name: 'Hostel C', type: 'hostel' })
    await user.click(await screen.findByRole('button', { name: 'Edit Hostel B' }))
    await user.click(screen.getByLabelText(/^Active/))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminUpdateUnit).toHaveBeenCalledWith('u-hb', { name: 'Hostel B', active: false })
  })

  it('shows a duplicate refusal', async () => {
    const api = admin({ adminCreateUnit: vi.fn().mockRejectedValue(new ApiError(409, 'This location already exists')) })
    const { user } = renderAt('/grievance/admin/locations', api)
    await user.click(await screen.findByRole('button', { name: /add a location/i }))
    await user.type(screen.getByLabelText(/^name/i), 'Hostel A')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
  })
})

describe('routing', () => {
  it('lists rows with names, marking default rows and deactivated people', async () => {
    const rows = [{ ...ROUTES[0], level1: { ...ROUTES[0].level1, active: false } }, ROUTES[1]]
    renderAt('/grievance/admin/routing', admin({ adminRouting: vi.fn().mockResolvedValue({ items: rows, total: 2 }) }))
    expect(await screen.findByText('Hostel A')).toBeInTheDocument()
    expect(screen.getByText('Default')).toBeInTheDocument()
    expect(screen.getByText('deactivated')).toBeInTheDocument()
  })

  it('adds a row for a location, offering only people who can handle tickets', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/routing', api)
    await user.click(await screen.findByRole('button', { name: /add a routing row/i }))
    await user.selectOptions(screen.getByLabelText(/^category/i), 'c-host')
    await user.selectOptions(await screen.findByLabelText(/^location/i), 'u-hb')
    await user.selectOptions(screen.getByLabelText(/level 0/i), 'u-care')
    await user.selectOptions(screen.getByLabelText(/level 1/i), 'u-ward')
    const options = within(screen.getByLabelText(/level 0/i)).getAllByRole('option').map((o) => o.textContent)
    expect(options.join()).not.toMatch(/Ravi Kumar/)                          // students are not offered
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminCreateRoute).toHaveBeenCalledWith({ category_id: 'c-host', unit_id: 'u-hb', level0_user_id: 'u-care', level1_user_id: 'u-ward', level2_user_id: null })
  })

  it('offers only officers for a confidential category', async () => {
    const { user } = renderAt('/grievance/admin/routing', admin())
    await user.click(await screen.findByRole('button', { name: /add a routing row/i }))
    await user.selectOptions(screen.getByLabelText(/^category/i), 'c-conf')
    const names = within(screen.getByLabelText(/level 0/i)).getAllByRole('option').map((o) => o.textContent)
    expect(names.some((n) => /Designated Officer 1/.test(n))).toBe(true)
    expect(names.some((n) => /Warden/.test(n))).toBe(false)
  })

  it('needs a category and a first person', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/routing', api)
    await user.click(await screen.findByRole('button', { name: /add a routing row/i }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/please choose a category/i)).toBeInTheDocument()
    expect(api.adminCreateRoute).not.toHaveBeenCalled()
  })

  it('edits the people of an existing row (clearing level 1 sends null)', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/routing', api)
    await user.click(await screen.findByRole('button', { name: 'Edit Hostel and housing Hostel A' }))
    await user.selectOptions(screen.getByLabelText(/level 1/i), '')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminUpdateRoute).toHaveBeenCalledWith('r1', { level0_user_id: 'u-care', level1_user_id: null, level2_user_id: null })
  })

  it('deletes only after confirmation and shows the server\'s refusal', async () => {
    const api = admin({ adminDeleteRoute: vi.fn().mockRejectedValue(new ApiError(409, 'Tickets already use this route.')) })
    const { user } = renderAt('/grievance/admin/routing', api)
    await user.click(await screen.findByRole('button', { name: 'Delete Hostel and housing Hostel A' }))
    expect(api.adminDeleteRoute).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(api.adminDeleteRoute).toHaveBeenCalledWith('r1')
    expect(await screen.findByRole('alert')).toHaveTextContent('Tickets already use this route.')
  })

  it('filters by category', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/routing', api)
    await screen.findByText('Hostel A')
    await user.selectOptions(screen.getByLabelText(/filter by category/i), 'c-lib')
    await waitFor(() => expect(api.adminRouting).toHaveBeenLastCalledWith(expect.objectContaining({ categoryId: 'c-lib' })))
  })
})

describe('CSV import (routing and users)', () => {
  it('previews first, saves only after, and sends dry-run as a real flag', async () => {
    const api = admin({ adminImport: vi.fn().mockImplementation(async (_k, _f, dry) => result({ dry_run: dry })) })
    const { user } = renderAt('/grievance/admin/routing', api)
    await screen.findByText('Hostel A')
    expect(screen.queryByRole('button', { name: /check the file/i })).not.toBeInTheDocument()
    await user.upload(screen.getByLabelText(/import routing from a csv file: choose/i), csv('routes.csv'))
    expect(screen.getByRole('button', { name: /save the valid rows/i })).toBeDisabled()          // nothing checked yet
    await user.click(screen.getByRole('button', { name: /check the file/i }))
    expect(api.adminImport).toHaveBeenLastCalledWith('routing', expect.objectContaining({ name: 'routes.csv' }), true)
    expect(await screen.findByText(/nothing has been saved yet/i)).toBeInTheDocument()
    expect(screen.getByText('Unknown category "Nonsense"')).toBeInTheDocument()
    expect(screen.getByText(/1 to add, 1 to update, 1 with problems/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /save the valid rows/i }))
    expect(api.adminImport).toHaveBeenLastCalledWith('routing', expect.objectContaining({ name: 'routes.csv' }), false)
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    await waitFor(() => expect(api.adminRouting.mock.calls.length).toBeGreaterThan(1))          // list reloaded
  })

  it('will not offer to save when nothing is valid, and forgets the preview when the file changes', async () => {
    const api = admin({ adminImport: vi.fn().mockResolvedValue(result({ created: 0, updated: 0, errors: 3 })) })
    const { user } = renderAt('/grievance/admin/routing', api)
    await screen.findByText('Hostel A')
    const input = screen.getByLabelText(/import routing from a csv file: choose/i)
    await user.upload(input, csv())
    await user.click(screen.getByRole('button', { name: /check the file/i }))
    await screen.findByText(/nothing has been saved yet/i)
    expect(screen.getByRole('button', { name: /save the valid rows/i })).toBeDisabled()
    await user.upload(input, csv('other.csv'))
    expect(screen.queryByText(/nothing has been saved yet/i)).not.toBeInTheDocument()
  })

  it('shows a file error from the server', async () => {
    const api = admin({ adminImport: vi.fn().mockRejectedValue(new ApiError(422, 'Missing column(s): level0_email. Download the template to see the format.')) })
    const { user } = renderAt('/grievance/admin/users', api)
    await screen.findByText('Ravi Kumar')
    await user.upload(screen.getByLabelText(/import users from a csv file: choose/i), csv())
    await user.click(screen.getByRole('button', { name: /check the file/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/missing column/i)
  })

  it('downloads the template', async () => {
    const api = admin()
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:x'); globalThis.URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { user } = renderAt('/grievance/admin/users', api)
    await screen.findByText('Ravi Kumar')
    await user.click(screen.getByRole('button', { name: /download the template/i }))
    expect(api.adminTemplate).toHaveBeenCalledWith('users')
    await waitFor(() => expect(click).toHaveBeenCalled())
    click.mockRestore()
  })
})

describe('users', () => {
  it('lists and filters', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/users', api)
    expect(await screen.findByText('Designated Officer 1')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/filter by role/i), 'officer')
    await waitFor(() => expect(api.adminUsers).toHaveBeenLastCalledWith(expect.objectContaining({ role: 'officer' })))
    await user.selectOptions(screen.getByLabelText(/filter by status/i), 'false')
    await waitFor(() => expect(api.adminUsers).toHaveBeenLastCalledWith(expect.objectContaining({ active: false })))
  })

  it('adds a user with a college email', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/users', api)
    await user.click(await screen.findByRole('button', { name: /add a user/i }))
    await user.type(screen.getByLabelText(/^name/i), 'New Clerk')
    await user.type(screen.getByLabelText(/college email/i), 'clerk@college.edu')
    await user.selectOptions(screen.getByLabelText(/^role/i), 'staff')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminCreateUser).toHaveBeenCalledWith({ name: 'New Clerk', email: 'clerk@college.edu', role: 'staff', department: null, hostel: null, room: null })
  })

  it('shows the server\'s email refusal', async () => {
    const api = admin({ adminCreateUser: vi.fn().mockRejectedValue(new ApiError(422, 'Email must be a valid @college.edu address')) })
    const { user } = renderAt('/grievance/admin/users', api)
    await user.click(await screen.findByRole('button', { name: /add a user/i }))
    await user.type(screen.getByLabelText(/^name/i), 'X')
    await user.type(screen.getByLabelText(/college email/i), 'x@gmail.com')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('valid @college.edu address')
  })

  it('deactivates someone and shows the routing warning', async () => {
    const api = admin({ adminUpdateUser: vi.fn().mockResolvedValue({ warnings: ['This person is in 3 routing row(s). Tickets skip deactivated people, but update those rows.'] }) })
    const { user } = renderAt('/grievance/admin/users', api)
    await user.click(await screen.findByRole('button', { name: 'Edit Warden' }))
    expect(screen.getByLabelText(/college email/i)).toBeDisabled()
    await user.click(screen.getByLabelText(/^Active/))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.adminUpdateUser).toHaveBeenCalledWith('u-ward', expect.objectContaining({ active: false, role: 'staff' }))
    expect(await screen.findByText(/in 3 routing row/)).toBeInTheDocument()
  })

  it('stops an admin from editing their own role or status', async () => {
    const mine = { ...USERS[0], id: ME.admin.id, name: 'Admin Office', role: 'admin' }
    const api = admin({ adminUsers: vi.fn().mockResolvedValue({ items: [mine], total: 1 }) })
    const { user } = renderAt('/grievance/admin/users', api)
    await user.click(await screen.findByRole('button', { name: 'Edit Admin Office' }))
    expect(screen.getByLabelText(/^role/i)).toBeDisabled()
    expect(screen.getByLabelText(/^Active/)).toBeDisabled()
  })
})

describe('change log', () => {
  it('shows who did what and filters by kind', async () => {
    const api = admin({ adminAudit: vi.fn().mockResolvedValue({ total: 1, items: [{ at: '2026-10-08T10:00:00Z', actor: 'admin@college.edu', action: 'update', entity: 'routing', entity_id: 'r1', detail: 'Hostel and housing / Hostel A' }] }) })
    const { user } = renderAt('/grievance/admin/audit', api)
    expect(await screen.findByText('Hostel and housing / Hostel A')).toBeInTheDocument()
    expect(screen.getByText('admin@college.edu')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/filter by kind/i), 'user')
    await waitFor(() => expect(api.adminAudit).toHaveBeenLastCalledWith(expect.objectContaining({ entity: 'user' })))
  })
})

describe('system health', () => {
  it('shows a healthy system calmly', async () => {
    renderAt('/grievance/admin/health', admin())
    expect(await screen.findByText('Running')).toBeInTheDocument()
    expect(screen.getByText('Configured')).toBeInTheDocument()
    expect(screen.getByText(/last ran 1 minute ago/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each([['stale', /has not run recently/i], ['never', /has never run/i]])('raises an alarm when the worker is %s', async (status, text) => {
    const api = admin({ adminHealth: vi.fn().mockResolvedValue({ ...HEALTH, worker: { ...HEALTH.worker, status, last_heartbeat: null, minutes_ago: null } }) })
    renderAt('/grievance/admin/health', api)
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
  })

  it('warns about unscanned uploads, test sign-in, no email and failed emails', async () => {
    const api = admin({ adminHealth: vi.fn().mockResolvedValue({
      ...HEALTH, email: { configured: false, waiting: 0, gave_up: 2, recent_failures: [{ notification_id: 'n1', to: 'a@college.edu', error: 'Email is not configured', attempts: 5, at: '2026-10-08T10:00:00Z' }] },
      checks: { database: 'ok', uploads_dir_writable: false, clamav_enabled: false, dev_login_enabled: true, watchdog_enabled: false }, overdue_tickets: 4 }) })
    renderAt('/grievance/admin/health', api)
    expect(await screen.findByText(/not virus-scanned/i)).toBeInTheDocument()
    expect(screen.getByText(/test sign-in is on/i)).toBeInTheDocument()
    expect(screen.getByText(/uploads will fail/i)).toBeInTheDocument()
    expect(screen.getByText('Not configured')).toBeInTheDocument()
    expect(screen.getByText('a@college.edu')).toBeInTheDocument()
    expect(screen.getByText(/watchdog that emails you/i)).toBeInTheDocument()
  })

  it('refreshes on request', async () => {
    const api = admin()
    const { user } = renderAt('/grievance/admin/health', api)
    await screen.findByText('Running')
    await user.click(screen.getByRole('button', { name: /refresh/i }))
    await waitFor(() => expect(api.adminHealth).toHaveBeenCalledTimes(2))
  })
})
