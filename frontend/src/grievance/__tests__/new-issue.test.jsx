import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { OPTIONS, fakeApi, renderAt, ticket } from '../../test/helpers'

const png = (name = 'ac.png', type = 'image/png') => new File([new Uint8Array(50)], name, { type })
const description = 'The AC in my room has not worked for two days now'

async function typeDescription(user, text = description) {
  await user.type(await screen.findByLabelText(/what is the problem/i), text)
}

describe('the report form', () => {
  it('suggests a category while typing and picks the student\'s own hostel', async () => {
    const api = fakeApi({
      classify: vi.fn().mockResolvedValue({
        suggested: { id: 'c-host', name: 'Hostel and housing' }, confidence: 'high', alternatives: [], confidential: false, urgent: false }),
    })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user)
    await waitFor(() => expect(api.classify).toHaveBeenCalled(), { timeout: 3000 })
    expect(api.classify.mock.calls.at(-1)[0]).toBe(description)
    await waitFor(() => expect(screen.getByLabelText(/^category/i)).toHaveValue('c-host'))
    expect(screen.getByText(/suggested from your description/i)).toBeInTheDocument()
    expect(await screen.findByLabelText(/which hostel/i)).toHaveValue('u-ha')          // Ravi lives in Hostel A
  })

  it('does not preselect when the system has no idea, and warns when it is unsure', async () => {
    const api = fakeApi({ classify: vi.fn().mockResolvedValue({ suggested: { id: 'c-other', name: 'Other' }, confidence: 'none', alternatives: [], confidential: false, urgent: false }) })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user)
    await waitFor(() => expect(api.classify).toHaveBeenCalled(), { timeout: 3000 })
    expect(screen.getByLabelText(/^category/i)).toHaveValue('')
    expect(await screen.findByText(/we are not sure about this one/i)).toBeInTheDocument()
  })

  it('never overwrites a category the student chose', async () => {
    const api = fakeApi({ classify: vi.fn().mockResolvedValue({ suggested: { id: 'c-host', name: 'Hostel and housing' }, confidence: 'high', alternatives: [], confidential: false, urgent: false }) })
    const { user } = renderAt('/grievance/new', api)
    await user.selectOptions(await screen.findByLabelText(/^category/i), 'c-lib')
    await typeDescription(user)
    await waitFor(() => expect(api.classify).toHaveBeenCalled(), { timeout: 3000 })
    expect(screen.getByLabelText(/^category/i)).toHaveValue('c-lib')
  })

  it('keeps working when the suggestion fails', async () => {
    const api = fakeApi({ classify: vi.fn().mockRejectedValue(new ApiError(500, 'boom')) })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user)
    await waitFor(() => expect(api.classify).toHaveBeenCalled(), { timeout: 3000 })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit/i })).toBeEnabled()
  })

  it('locks the confidential box and explains when the text looks sensitive', async () => {
    const api = fakeApi({ classify: vi.fn().mockResolvedValue({ suggested: { id: 'c-conf', name: 'x' }, confidence: 'high', alternatives: [], confidential: true, urgent: false }) })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user, 'A senior keeps harassing me every night')
    const box = await screen.findByRole('checkbox', { name: /keep this confidential/i })
    await waitFor(() => expect(box).toBeChecked(), { timeout: 3000 })
    expect(box).toBeDisabled()
    expect(screen.getByText(/this looks sensitive/i)).toBeInTheDocument()
    expect(screen.getByText(/only by designated officers/i)).toBeInTheDocument()
  })

  it('is confidential when the student chooses the confidential category', async () => {
    const { user } = renderAt('/grievance/new', fakeApi())
    await user.selectOptions(await screen.findByLabelText(/^category/i), 'c-conf')
    expect(screen.getByRole('checkbox', { name: /keep this confidential/i })).toBeChecked()
  })

  it('fills the description from the chatbot link', async () => {
    renderAt('/grievance/new?text=My%20fan%20is%20broken', fakeApi())
    expect(await screen.findByLabelText(/what is the problem/i)).toHaveValue('My fan is broken')
  })

  it('asks for the missing pieces and sends nothing', async () => {
    const { user, api } = renderAt('/grievance/new', fakeApi())
    await user.click(await screen.findByRole('button', { name: /submit/i }))
    expect(await screen.findByText(/please describe the problem/i)).toBeInTheDocument()
    expect(screen.getByText(/choose the category that fits best/i)).toBeInTheDocument()
    expect(api.createIssue).not.toHaveBeenCalled()
  })
})

describe('sending it', () => {
  it('creates the ticket, then uploads each file in order, then shows the ticket', async () => {
    const order = []
    const api = fakeApi({
      createIssue: vi.fn().mockImplementation(async () => { order.push('create'); return ticket({ id: 't9', ticket_no: 'GRV-2026-000009' }) }),
      uploadAttachment: vi.fn().mockImplementation(async (_id, f) => { order.push(f.name); return {} }),
      getIssue: vi.fn().mockResolvedValue(ticket({ id: 't9', ticket_no: 'GRV-2026-000009' })),
    })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user)
    await user.selectOptions(screen.getByLabelText(/^category/i), 'c-host')
    await user.type(screen.getByLabelText(/room, floor/i), 'A-101')
    await user.upload(screen.getByLabelText('Attach files'), [png('front.png'), png('back.png')])
    expect(screen.getByText('front.png')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /submit/i }))

    expect(await screen.findByText(/your problem was received/i)).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/grievance/issues/t9')
    expect(order).toEqual(['create', 'front.png', 'back.png'])
    expect(api.createIssue).toHaveBeenCalledWith({
      description, category_id: 'c-host', unit_id: 'u-ha', location_text: 'A-101', confidential: false })
    expect(api.uploadAttachment.mock.calls.map((c) => c[0])).toEqual(['t9', 't9'])
  })

  it('keeps the ticket and says which file failed', async () => {
    const api = fakeApi({
      createIssue: vi.fn().mockResolvedValue(ticket({ id: 't9' })),
      uploadAttachment: vi.fn().mockRejectedValueOnce(new ApiError(415, 'Only JPG, PNG and PDF files are accepted')).mockResolvedValue({}),
      getIssue: vi.fn().mockResolvedValue(ticket({ id: 't9' })),
    })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user)
    await user.selectOptions(screen.getByLabelText(/^category/i), 'c-lib')
    await user.upload(screen.getByLabelText('Attach files'), [png('bad.png'), png('good.png')])
    await user.click(screen.getByRole('button', { name: /submit/i }))
    expect(await screen.findByText(/some files could not be added/i)).toBeInTheDocument()
    expect(screen.getByText(/bad\.png: Only JPG, PNG and PDF/)).toBeInTheDocument()
    expect(api.uploadAttachment).toHaveBeenCalledTimes(2)                 // the second file still went
  })

  it('points to the existing ticket on a duplicate and stays on the form', async () => {
    const api = fakeApi({
      createIssue: vi.fn().mockRejectedValue(new ApiError(409, 'You already have an open ticket for this.', { existing_ticket_id: 't5', existing_ticket_no: 'GRV-2026-000005' })),
    })
    const { user } = renderAt('/grievance/new', api)
    await typeDescription(user)
    await user.selectOptions(screen.getByLabelText(/^category/i), 'c-host')
    await user.click(screen.getByRole('button', { name: /submit/i }))
    const link = await screen.findByRole('link', { name: /open GRV-2026-000005/i })
    expect(link).toHaveAttribute('href', '/grievance/issues/t5')
    expect(screen.getByLabelText(/what is the problem/i)).toHaveValue(description)       // nothing lost
  })

  it.each([[429, 'Daily limit of new tickets reached.'], [503, 'No route is configured for this category.']])(
    'shows the server message for %i', async (status, message) => {
      const api = fakeApi({ createIssue: vi.fn().mockRejectedValue(new ApiError(status, message)) })
      const { user } = renderAt('/grievance/new', api)
      await typeDescription(user)
      await user.selectOptions(screen.getByLabelText(/^category/i), 'c-lib')
      await user.click(screen.getByRole('button', { name: /submit/i }))
      expect(await screen.findByRole('alert')).toHaveTextContent(message)
    })

  it('refuses a wrong file type before sending', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const { api } = renderAt('/grievance/new', fakeApi())
    const input = await screen.findByLabelText('Attach files')
    await user.upload(input, new File(['x'], 'virus.exe', { type: 'application/octet-stream' }))
    expect(await screen.findByText(/"virus\.exe" is not a JPG, PNG or PDF file/)).toBeInTheDocument()
    expect(screen.queryByText('virus.exe')).not.toBeInTheDocument()
    expect(api.createIssue).not.toHaveBeenCalled()
  })

  it('lets the student remove a chosen file', async () => {
    const { user } = renderAt('/grievance/new', fakeApi())
    await user.upload(await screen.findByLabelText('Attach files'), png('one.png'))
    await user.click(screen.getByRole('button', { name: /remove one\.png/i }))
    expect(screen.queryByText('one.png')).not.toBeInTheDocument()
  })

  it('shows the privacy notice about photos', async () => {
    renderAt('/grievance/new', fakeApi())
    expect(await screen.findByText(/photos can contain the place where they were taken/i)).toBeInTheDocument()
  })
})

describe('my issues', () => {
  it('lists tickets, filters by status and loads more', async () => {
    const { listItem, page } = await import('../../test/helpers')
    const api = fakeApi({
      myIssues: vi.fn()
        .mockResolvedValueOnce(page([listItem({ id: 'a', ticket_no: 'GRV-1' })], 2))
        .mockResolvedValueOnce(page([listItem({ id: 'b', ticket_no: 'GRV-2', status: 'NEEDS_INFO' })], 2))
        .mockResolvedValue(page([], 0)),
    })
    const { user } = renderAt('/grievance/issues', api)
    expect(await screen.findByText('GRV-1')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /show more/i }))
    expect(await screen.findByText('GRV-2')).toBeInTheDocument()
    expect(within(screen.getByText('GRV-2').closest('a')).getByText('Needs your reply')).toBeInTheDocument()
    expect(api.myIssues.mock.calls[1][0]).toMatchObject({ offset: 1 })
    await user.selectOptions(screen.getByLabelText(/filter by status/i), 'CLOSED')
    expect(await screen.findByText(/no issues with this status/i)).toBeInTheDocument()
    expect(api.myIssues.mock.calls.at(-1)[0]).toMatchObject({ status: 'CLOSED', offset: 0 })
  })

  it('invites the student to report something when the list is empty', async () => {
    renderAt('/grievance/issues', fakeApi())
    expect(await screen.findByText(/you have not reported anything yet/i)).toBeInTheDocument()
  })

  it('shows the error with a retry', async () => {
    const { page } = await import('../../test/helpers')
    const api = fakeApi({ myIssues: vi.fn().mockRejectedValueOnce(new ApiError(500, 'x')).mockResolvedValue(page([])) })
    const { user } = renderAt('/grievance/issues', api)
    await user.click(await screen.findByRole('button', { name: /try again/i }))
    expect(await screen.findByText(/you have not reported anything yet/i)).toBeInTheDocument()
  })
})
