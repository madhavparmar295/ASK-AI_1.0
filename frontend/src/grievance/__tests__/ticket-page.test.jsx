import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { ME, REPORTER_INFO, fakeApi, renderAt, ticket } from '../../test/helpers'

const OPEN_REPORTER = ['reply', 'cancel', 'upload']
const STAFF_ACTIONS = ['start', 'request_info', 'resolve', 'escalate', 'reassign', 'upload']
const buttons = () => screen.queryAllByRole('button').map((b) => b.textContent.trim())

function asStaff(t, me = ME.staff, extra = {}) {
  return fakeApi({ me: vi.fn().mockResolvedValue(me), getIssue: vi.fn().mockResolvedValue(t), ...extra })
}

describe('what each person sees on a ticket', () => {
  it('shows the reporter their own ticket with student-friendly buttons only', async () => {
    renderAt('/grievance/issues/t1', fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ status: 'NEEDS_INFO', actions: OPEN_REPORTER })) }))
    expect(await screen.findByText('GRV-2026-000001')).toBeInTheDocument()
    expect(screen.getByText('Needs your reply')).toBeInTheDocument()
    const b = buttons()
    expect(b).toEqual(expect.arrayContaining(['Reply', 'Cancel this ticket', 'Add a file']))
    expect(b).not.toContain('Start work')
    expect(b).not.toContain('Mark as resolved')
    expect(screen.queryByText(/reported by/i)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back/i })).toHaveAttribute('href', '/grievance/issues')
  })

  it('shows staff who reported it, plus their buttons', async () => {
    renderAt('/grievance/issues/t1', asStaff(ticket({ reporter: REPORTER_INFO, actions: STAFF_ACTIONS })))
    expect(await screen.findByText(/reported by/i)).toBeInTheDocument()
    expect(screen.getByText(/Ravi Kumar/)).toBeInTheDocument()
    expect(screen.getByText(/CSE · Hostel A · A-101/)).toBeInTheDocument()
    expect(buttons()).toEqual(expect.arrayContaining(['Start work', 'Ask for information', 'Mark as resolved', 'Escalate', 'Reassign']))
    expect(buttons()).not.toContain('Cancel this ticket')
    expect(screen.getByText('Waiting for work')).toBeInTheDocument()
  })

  it('shows no action box when nothing can be done', async () => {
    renderAt('/grievance/issues/t1', fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ status: 'CLOSED', actions: [] })) }))
    await screen.findByText('GRV-2026-000001')
    expect(screen.queryByText(/what would you like to do/i)).not.toBeInTheDocument()
  })

  it('lists files as links to the download address', async () => {
    const t = ticket({ attachments: [{ id: 'a1', original_name: 'ac.png', mime_type: 'image/png', size_bytes: 2048, scan_status: 'not_scanned', uploaded_by_me: true, created_at: '2026-10-08T10:00:00Z' }] })
    renderAt('/grievance/issues/t1', fakeApi({ getIssue: vi.fn().mockResolvedValue(t) }))
    const link = await screen.findByRole('link', { name: /ac\.png/i })
    expect(link).toHaveAttribute('href', '/api/grievance/attachments/a1')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('marks internal events for staff only and renders text safely', async () => {
    const events = [
      { type: 'assignment', text: 'Reassigned to <b>B</b>', actor: 'Warden', created_at: '2026-10-08T11:00:00Z', internal: true },
      { type: 'status', text: '<script>alert(1)</script>', actor: 'System', created_at: '2026-10-08T12:00:00Z', internal: false },
    ]
    renderAt('/grievance/issues/t1', asStaff(ticket({ reporter: REPORTER_INFO, events })))
    expect(await screen.findByText('internal')).toBeInTheDocument()
    expect(screen.getByText('Reassigned to <b>B</b>')).toBeInTheDocument()            // shown as text, not as HTML
    expect(document.querySelector('script')).toBeNull()
  })

  it('tells the reporter of a confidential ticket what that means', async () => {
    renderAt('/grievance/issues/t1', fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ confidential: true, assignee: null })) }))
    expect(await screen.findByText('Confidential')).toBeInTheDocument()
    expect(screen.getByText(/only designated officers can see it/i)).toBeInTheDocument()
    expect(screen.queryByText(/handled by/i)).not.toBeInTheDocument()
  })

  it('shows overdue deadlines in red wording', async () => {
    renderAt('/grievance/issues/t1', fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ due_at: new Date(Date.now() - 3 * 3600e3).toISOString() })) }))
    expect(await screen.findByText(/overdue by 3 h/)).toBeInTheDocument()
  })

  it('explains a missing ticket without saying why', async () => {
    renderAt('/grievance/issues/zzz', fakeApi({ getIssue: vi.fn().mockRejectedValue(new ApiError(404, 'Not found')) }))
    expect(await screen.findByText(/not found, or you do not have access/i)).toBeInTheDocument()
  })

  it('shows feedback that was already given', async () => {
    renderAt('/grievance/issues/t1', fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ status: 'CLOSED', feedback: { rating: 4, comment: 'Quick' } })) }))
    expect(await screen.findByText(/feedback given: 4\/5 · Quick/i)).toBeInTheDocument()
  })
})

describe('reporter actions', () => {
  it('sends a reply and shows the updated ticket', async () => {
    const after = ticket({ status: 'IN_PROGRESS', actions: OPEN_REPORTER })
    const api = fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ status: 'NEEDS_INFO', actions: OPEN_REPORTER })), reply: vi.fn().mockResolvedValue(after) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Reply' }))
    await user.type(screen.getByLabelText(/your message/i), 'The left unit')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(api.reply).toHaveBeenCalledWith('t1', 'The left unit')
    expect(await screen.findByText('In progress')).toBeInTheDocument()
    expect(await screen.findByText('Reply sent')).toBeInTheDocument()                    // toast
  })

  it('does not send an empty reply', async () => {
    const api = fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ actions: OPEN_REPORTER })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Reply' }))
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText(/please write something first/i)).toBeInTheDocument()
    expect(api.reply).not.toHaveBeenCalled()
  })

  it('cancels only after the student confirms in a dialog', async () => {
    const api = fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ actions: OPEN_REPORTER })), cancel: vi.fn().mockResolvedValue(ticket({ status: 'CANCELLED', actions: [] })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Cancel this ticket' }))
    const dialog = screen.getByRole('dialog', { name: /cancel this ticket/i })
    expect(api.cancel).not.toHaveBeenCalled()
    await user.type(within(dialog).getByLabelText(/reason/i), 'Fixed it myself')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel ticket' }))
    expect(api.cancel).toHaveBeenCalledWith('t1', 'Fixed it myself')
    expect(await screen.findByText('Cancelled')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps the ticket when the student chooses "Keep it" or presses Escape', async () => {
    const api = fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ actions: OPEN_REPORTER })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Cancel this ticket' }))
    await user.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel this ticket' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.cancel).not.toHaveBeenCalled()
  })

  it('confirms a fix with one click', async () => {
    const api = fakeApi({
      getIssue: vi.fn().mockResolvedValue(ticket({ status: 'RESOLVED', actions: ['confirm', 'reopen'] })),
      confirm: vi.fn().mockResolvedValue(ticket({ status: 'CLOSED', actions: ['feedback'] })),
    })
    const { user } = renderAt('/grievance/issues/t1', api)
    expect(await screen.findByText('Fixed? Please confirm')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Yes, it is fixed' }))
    expect(api.confirm).toHaveBeenCalledWith('t1')
    expect(await screen.findByRole('button', { name: 'Give feedback' })).toBeInTheDocument()
  })

  it('needs a reason to say it is not fixed', async () => {
    const api = fakeApi({
      getIssue: vi.fn().mockResolvedValue(ticket({ status: 'RESOLVED', actions: ['confirm', 'reopen'] })),
      reopen: vi.fn().mockResolvedValue(ticket({ status: 'ASSIGNED', actions: OPEN_REPORTER })),
    })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'It is not fixed' }))
    await user.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(api.reopen).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText(/what is still wrong/i), 'Still too hot')
    await user.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(api.reopen).toHaveBeenCalledWith('t1', 'Still too hot')
    expect(await screen.findByText('Waiting for work')).toBeInTheDocument()
  })

  it('needs a star rating, then sends feedback and reloads', async () => {
    const api = fakeApi({
      getIssue: vi.fn().mockResolvedValueOnce(ticket({ status: 'CLOSED', actions: ['feedback'] }))
        .mockResolvedValue(ticket({ status: 'CLOSED', actions: [], feedback: { rating: 4, comment: 'Fast' } })),
    })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Give feedback' }))
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(await screen.findByText(/please choose a rating/i)).toBeInTheDocument()
    expect(api.feedback).not.toHaveBeenCalled()
    await user.click(screen.getByRole('radio', { name: '4 out of 5' }))
    await user.type(screen.getByLabelText(/anything to add/i), 'Fast')
    await user.click(screen.getByRole('button', { name: 'Send feedback' }))
    expect(api.feedback).toHaveBeenCalledWith('t1', 4, 'Fast')
    expect(await screen.findByText(/feedback given: 4\/5/i)).toBeInTheDocument()
  })

  it('adds a file to an open ticket and reloads', async () => {
    const api = fakeApi({ getIssue: vi.fn().mockResolvedValue(ticket({ actions: OPEN_REPORTER })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Add a file' }))
    await user.upload(screen.getByLabelText('Attach files'), new File([new Uint8Array(10)], 'more.png', { type: 'image/png' }))
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(api.uploadAttachment).toHaveBeenCalledWith('t1', expect.objectContaining({ name: 'more.png' }))
    await waitFor(() => expect(api.getIssue).toHaveBeenCalledTimes(2))
  })

  it('shows the server message when an action is refused and keeps the form', async () => {
    const api = fakeApi({
      getIssue: vi.fn().mockResolvedValue(ticket({ actions: OPEN_REPORTER })),
      reply: vi.fn().mockRejectedValue(new ApiError(409, 'This ticket is not open.')),
    })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Reply' }))
    await user.type(screen.getByLabelText(/your message/i), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This ticket is not open.')
    expect(screen.getByLabelText(/your message/i)).toHaveValue('hello')
  })
})

describe('staff actions', () => {
  it('starts work with one click', async () => {
    const api = asStaff(ticket({ reporter: REPORTER_INFO, actions: STAFF_ACTIONS }), ME.staff, { start: vi.fn().mockResolvedValue(ticket({ reporter: REPORTER_INFO, status: 'IN_PROGRESS', actions: ['request_info', 'resolve'] })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Start work' }))
    expect(api.start).toHaveBeenCalledWith('t1')
    expect(await screen.findByText('In progress')).toBeInTheDocument()
    expect(buttons()).not.toContain('Start work')
  })

  it('needs a note to resolve and sends it', async () => {
    const api = asStaff(ticket({ reporter: REPORTER_INFO, status: 'IN_PROGRESS', actions: ['request_info', 'resolve'] }), ME.staff,
      { resolve: vi.fn().mockResolvedValue(ticket({ reporter: REPORTER_INFO, status: 'RESOLVED', actions: [] })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Mark as resolved' }))
    await user.click(screen.getByRole('button', { name: 'Resolve' }))
    expect(api.resolve).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText(/what was done/i), 'Replaced the capacitor')
    await user.click(screen.getByRole('button', { name: 'Resolve' }))
    expect(api.resolve).toHaveBeenCalledWith('t1', 'Replaced the capacitor')
    expect(await screen.findByText('Resolved')).toBeInTheDocument()
  })

  it('asks the reporter for information', async () => {
    const api = asStaff(ticket({ reporter: REPORTER_INFO, actions: ['request_info'] }), ME.staff,
      { requestInfo: vi.fn().mockResolvedValue(ticket({ reporter: REPORTER_INFO, status: 'NEEDS_INFO', actions: [] })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Ask for information' }))
    await user.type(screen.getByLabelText(/what do you need to know/i), 'Which unit?')
    await user.click(screen.getByRole('button', { name: 'Send question' }))
    expect(api.requestInfo).toHaveBeenCalledWith('t1', 'Which unit?')
    expect(await screen.findByText('Waiting for reply')).toBeInTheDocument()
  })

  it('escalates with a reason', async () => {
    const api = asStaff(ticket({ reporter: REPORTER_INFO, actions: ['escalate', 'reassign'] }), ME.head,
      { escalate: vi.fn().mockResolvedValue(ticket({ reporter: REPORTER_INFO, status: 'ESCALATED', escalation_level: 2, actions: [] })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Escalate' }))
    await user.type(screen.getByLabelText(/why/i), 'No response for two days')
    await user.click(screen.getAllByRole('button', { name: 'Escalate' }).at(-1))
    expect(api.escalate).toHaveBeenCalledWith('t1', 'No response for two days')
    expect(await screen.findByText('Escalated')).toBeInTheDocument()
  })

  it('reassigns to someone from the list the server provides', async () => {
    const api = asStaff(ticket({ reporter: REPORTER_INFO, actions: ['reassign'] }), ME.head,
      { reassign: vi.fn().mockResolvedValue(ticket({ reporter: REPORTER_INFO, assignee: { id: 'u-cb', name: 'Caretaker Hostel B' }, actions: [] })) })
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Reassign' }))
    await user.selectOptions(await screen.findByLabelText(/assign to/i), 'u-cb')
    await user.type(screen.getByLabelText(/reason/i), 'On leave')
    await user.click(screen.getAllByRole('button', { name: 'Reassign' }).at(-1))
    expect(api.reassign).toHaveBeenCalledWith('t1', 'u-cb', 'On leave')
    expect(await screen.findByText('Caretaker Hostel B')).toBeInTheDocument()
  })

  it('does not reassign without a person and a reason', async () => {
    const api = asStaff(ticket({ reporter: REPORTER_INFO, actions: ['reassign'] }), ME.head)
    const { user } = renderAt('/grievance/issues/t1', api)
    await user.click(await screen.findByRole('button', { name: 'Reassign' }))
    await screen.findByRole('option', { name: /Caretaker Hostel B/ })
    await user.click(screen.getAllByRole('button', { name: 'Reassign' }).at(-1))
    expect(await screen.findByText(/choose a person and write a reason/i)).toBeInTheDocument()
    expect(api.reassign).not.toHaveBeenCalled()
  })
})
