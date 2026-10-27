import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { ME, fakeApi, listItem, page, renderAt, ticket } from '../../test/helpers'

const staffApi = (me, over = {}) => fakeApi({ me: vi.fn().mockResolvedValue(me), ...over })

describe('staff lists', () => {
  it('shows my queue with who reported each ticket and when it is due', async () => {
    const api = staffApi(ME.staff, {
      staffIssues: vi.fn().mockResolvedValue(page([
        listItem({ id: 'a', ticket_no: 'GRV-A', reporter_name: 'Ravi Kumar', due_at: new Date(Date.now() + 5 * 3600e3).toISOString() }),
        listItem({ id: 'b', ticket_no: 'GRV-B', reporter_name: 'Priya Sharma', status: 'IN_PROGRESS', overdue: true, urgent: true, due_at: new Date(Date.now() - 2 * 3600e3).toISOString() }),
      ])),
    })
    renderAt('/grievance/queue', api)
    expect(await screen.findByText('GRV-A')).toBeInTheDocument()
    expect(api.staffIssues).toHaveBeenCalledWith(expect.objectContaining({ scope: 'mine', overdue: false }))
    const b = screen.getByText('GRV-B').closest('a')
    expect(within(b).getByText(/from Priya Sharma/)).toBeInTheDocument()
    expect(within(b).getByText(/overdue by 2 h/)).toBeInTheDocument()
    expect(within(b).getByText('Urgent')).toBeInTheDocument()
    expect(within(b).getByText('In progress')).toBeInTheDocument()
    expect(b).toHaveAttribute('href', '/grievance/issues/b')
    expect(screen.getByText('2 tickets')).toBeInTheDocument()
  })

  it('filters by status and overdue only, starting again from the first page', async () => {
    const api = staffApi(ME.staff, { staffIssues: vi.fn().mockResolvedValue(page([listItem()])) })
    const { user } = renderAt('/grievance/queue', api)
    await screen.findByText('GRV-2026-000001')
    await user.selectOptions(screen.getByLabelText(/filter by status/i), 'IN_PROGRESS')
    await waitFor(() => expect(api.staffIssues).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'IN_PROGRESS', offset: 0 })))
    await user.click(screen.getByRole('checkbox', { name: /overdue only/i }))
    await waitFor(() => expect(api.staffIssues).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'IN_PROGRESS', overdue: true })))
  })

  it('loads more tickets on request', async () => {
    const api = staffApi(ME.staff, {
      staffIssues: vi.fn().mockResolvedValueOnce(page([listItem({ id: 'a', ticket_no: 'GRV-A' })], 2))
        .mockResolvedValueOnce(page([listItem({ id: 'b', ticket_no: 'GRV-B' })], 2)),
    })
    const { user } = renderAt('/grievance/queue', api)
    await screen.findByText('GRV-A')
    await user.click(screen.getByRole('button', { name: /show more/i }))
    expect(await screen.findByText('GRV-B')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /show more/i })).not.toBeInTheDocument()
  })

  it('uses the team scope for heads', async () => {
    const api = staffApi(ME.head, { staffIssues: vi.fn().mockResolvedValue(page([listItem()])) })
    renderAt('/grievance/team', api)
    await screen.findByText('GRV-2026-000001')
    expect(api.staffIssues).toHaveBeenCalledWith(expect.objectContaining({ scope: 'team' }))
  })

  it('has a separate overdue list', async () => {
    const api = staffApi(ME.head, { staffOverdue: vi.fn().mockResolvedValue(page([listItem({ ticket_no: 'GRV-LATE', overdue: true })])) })
    renderAt('/grievance/overdue', api)
    expect(await screen.findByText('GRV-LATE')).toBeInTheDocument()
    expect(api.staffOverdue).toHaveBeenCalled()
    expect(api.staffIssues).not.toHaveBeenCalled()
    expect(screen.queryByLabelText(/filter by status/i)).not.toBeInTheDocument()
  })

  it('says so when nothing is waiting', async () => {
    renderAt('/grievance/queue', staffApi(ME.staff))
    expect(await screen.findByText(/nothing is assigned to you right now/i)).toBeInTheDocument()
    renderAt('/grievance/overdue', staffApi(ME.head))
    expect(await screen.findByText(/nothing is overdue/i)).toBeInTheDocument()
  })

  it('shows confidential tickets to officers with a badge, without any details beyond what the server sent', async () => {
    const api = staffApi(ME.officer, { staffIssues: vi.fn().mockResolvedValue(page([listItem({ confidential: true, reporter_name: 'Priya Sharma' })])) })
    renderAt('/grievance/queue', api)
    expect(await screen.findByText('Confidential')).toBeInTheDocument()
  })

  it('shows an error with retry', async () => {
    const api = staffApi(ME.staff, { staffIssues: vi.fn().mockRejectedValueOnce(new ApiError(500, 'x')).mockResolvedValue(page([])) })
    const { user } = renderAt('/grievance/queue', api)
    await user.click(await screen.findByRole('button', { name: /try again/i }))
    expect(await screen.findByText(/nothing is assigned/i)).toBeInTheDocument()
  })
})

describe('notifications', () => {
  it('shows the unread count on the bell', async () => {
    renderAt('/grievance/issues', fakeApi({ unreadCount: vi.fn().mockResolvedValue({ unread: 3 }) }))
    expect(await screen.findByRole('link', { name: 'Notifications, 3 unread' })).toHaveAttribute('href', '/grievance/notifications')
  })

  it('lists notifications, marks one read and opens its ticket', async () => {
    const items = [
      { id: 'n1', ticket_id: 't1', text: 'Ticket GRV-1 was marked as resolved.', read: false, created_at: '2026-10-08T10:00:00Z' },
      { id: 'n2', ticket_id: null, text: 'Older one', read: true, created_at: '2026-10-07T10:00:00Z' },
    ]
    const api = fakeApi({ notifications: vi.fn().mockResolvedValue({ items, total: 2, unread: 1 }), getIssue: vi.fn().mockResolvedValue(ticket()) })
    const { user } = renderAt('/grievance/notifications', api)
    await user.click(await screen.findByText('Ticket GRV-1 was marked as resolved.'))
    expect(api.markRead).toHaveBeenCalledWith('n1')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/grievance/issues/t1'))
  })

  it('marks everything read', async () => {
    const items = [{ id: 'n1', ticket_id: 't1', text: 'Something happened', read: false, created_at: '2026-10-08T10:00:00Z' }]
    const api = fakeApi({ notifications: vi.fn().mockResolvedValue({ items, total: 1, unread: 1 }) })
    const { user } = renderAt('/grievance/notifications', api)
    await screen.findByText('Something happened')
    await user.click(screen.getByRole('button', { name: /mark all as read/i }))
    expect(api.readAll).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: /mark all as read/i })).toBeDisabled())
    expect(screen.queryByLabelText('Unread')).not.toBeInTheDocument()
  })

  it('shows an empty state', async () => {
    renderAt('/grievance/notifications', fakeApi())
    expect(await screen.findByText(/no notifications yet/i)).toBeInTheDocument()
  })

  it('ignores a failing unread count so the page still works', async () => {
    renderAt('/grievance/issues', fakeApi({ unreadCount: vi.fn().mockRejectedValue(new ApiError(500, 'x')) }))
    expect(await screen.findByRole('link', { name: 'Notifications' })).toBeInTheDocument()
  })
})
