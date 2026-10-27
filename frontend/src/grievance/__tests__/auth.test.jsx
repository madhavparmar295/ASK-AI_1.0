import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { ME, fakeApi, page, renderAt } from '../../test/helpers'

describe('signing in', () => {
  it('shows the sign-in page when there is no session', async () => {
    const api = fakeApi({ me: vi.fn().mockRejectedValue(new ApiError(401, 'Please sign in again.')) })
    renderAt('/grievance/issues', api)
    expect(await screen.findByRole('heading', { name: /sign in to the grievance system/i })).toBeInTheDocument()
    expect(screen.getByText(/sign-in is not configured/i)).toBeInTheDocument()       // no Google client, no dev users
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('lets a developer sign in as a test user, then shows the app', async () => {
    const devUsers = [{ email: 'ravi@college.edu', name: 'Ravi Kumar', role: 'student' }, { email: 'admin@college.edu', name: 'Admin', role: 'admin' }]
    const api = fakeApi({ me: vi.fn().mockRejectedValue(new ApiError(401, 'x')), devUsers: vi.fn().mockResolvedValue(devUsers) })
    const { user } = renderAt('/grievance/issues', api)
    await user.click(await screen.findByRole('button', { name: /^sign in$/i }))
    expect(api.devLogin).toHaveBeenCalledWith('ravi@college.edu')
    expect(await screen.findByRole('heading', { name: 'My issues' })).toBeInTheDocument()
  })

  it('shows the server message when sign-in is refused', async () => {
    const api = fakeApi({
      me: vi.fn().mockRejectedValue(new ApiError(401, 'x')),
      devUsers: vi.fn().mockResolvedValue([{ email: 'x@college.edu', name: 'X', role: 'student' }]),
      devLogin: vi.fn().mockRejectedValue(new ApiError(403, 'This account is deactivated')),
    })
    const { user } = renderAt('/grievance', api)
    await user.click(await screen.findByRole('button', { name: /^sign in$/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This account is deactivated')
  })

  it('shows a retry when the server cannot be reached', async () => {
    const api = fakeApi({ me: vi.fn().mockRejectedValueOnce(new ApiError(0, 'Could not reach the server.')).mockResolvedValue(ME.student) })
    const { user } = renderAt('/grievance/issues', api)
    expect(await screen.findByText(/could not reach the server/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByRole('heading', { name: 'My issues' })).toBeInTheDocument()
  })

  it('goes back to the sign-in page when the session ends', async () => {
    const api = fakeApi({ myIssues: vi.fn().mockResolvedValue(page([])) })
    renderAt('/grievance/issues', api)
    await screen.findByRole('heading', { name: 'My issues' })
    const onExpire = api.client.setOnUnauthorized.mock.calls[0][0]
    onExpire()
    expect(await screen.findByRole('heading', { name: /sign in to the grievance system/i })).toBeInTheDocument()
  })

  it('signs out', async () => {
    const api = fakeApi()
    const { user } = renderAt('/grievance/issues', api)
    await user.click(await screen.findByRole('button', { name: /sign out/i }))
    expect(api.logout).toHaveBeenCalled()
    expect(await screen.findByRole('heading', { name: /sign in to the grievance system/i })).toBeInTheDocument()
  })
})

describe('where each person lands and what they can open', () => {
  it('sends a student to My issues and a staff member to their queue', async () => {
    renderAt('/grievance', fakeApi())
    expect(await screen.findByRole('heading', { name: 'My issues' })).toBeInTheDocument()
    const api = fakeApi({ me: vi.fn().mockResolvedValue(ME.staff) })
    renderAt('/grievance', api)
    expect(await screen.findByRole('heading', { name: 'My queue' })).toBeInTheDocument()
  })

  it('shows the menu that matches the role', async () => {
    renderAt('/grievance/issues', fakeApi({ me: vi.fn().mockResolvedValue(ME.head) }))
    const nav = await screen.findByRole('navigation', { name: /grievance sections/i })
    expect(nav).toHaveTextContent(/My queue.*Team.*Overdue.*My issues.*Report a problem/)
  })

  it('shows "page not found" for staff pages when a student types the address', async () => {
    renderAt('/grievance/queue', fakeApi())
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })

  it('shows "page not found" for the admin area to non-admins, and the dashboard to admins', async () => {
    renderAt('/grievance/admin', fakeApi({ me: vi.fn().mockResolvedValue(ME.staff) }))
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
    renderAt('/grievance/admin', fakeApi({ me: vi.fn().mockResolvedValue(ME.admin) }))
    expect(await screen.findByText('Open tickets')).toBeInTheDocument()
  })

  it('shows "page not found" for unknown addresses', async () => {
    renderAt('/grievance/nope', fakeApi())
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })
})
