import { describe, expect, it, vi } from 'vitest'
import { ApiError, createClient, detailToMessage } from '../api/client'
import { createApi } from '../api/endpoints'

function reply(status, body, type = 'application/json') {
  return Promise.resolve(new Response(body === undefined ? null : typeof body === 'string' ? body : JSON.stringify(body), {
    status, headers: body === undefined ? {} : { 'content-type': type },
  }))
}
function setup(fn) {
  const fetchImpl = vi.fn(fn)
  return { fetchImpl, client: createClient({ baseUrl: '/api/grievance', fetchImpl }) }
}

describe('requests', () => {
  it('sends cookies, JSON, and no CSRF header on GET', async () => {
    const { client, fetchImpl } = setup(() => reply(200, { ok: 1 }))
    client.setCsrf('tok')
    await client.get('/me')
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/grievance/me')
    expect(init.credentials).toBe('include')
    expect(init.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('adds the CSRF token to every change, from memory or the cookie', async () => {
    const { client, fetchImpl } = setup(() => reply(200, {}))
    client.setCsrf('from-memory')
    await client.post('/x', { a: 1 })
    expect(fetchImpl.mock.calls[0][1].headers['X-CSRF-Token']).toBe('from-memory')
    expect(fetchImpl.mock.calls[0][1].body).toBe('{"a":1}')
    client.setCsrf(null)
    document.cookie = 'grievance_csrf=from-cookie'
    await client.post('/x')
    expect(fetchImpl.mock.calls[1][1].headers['X-CSRF-Token']).toBe('from-cookie')
    document.cookie = 'grievance_csrf=; max-age=0'
  })

  it('does not set Content-Type on uploads so the browser adds the boundary', async () => {
    const { client, fetchImpl } = setup(() => reply(201, {}))
    const form = new FormData(); form.append('file', new Blob(['x']), 'a.png')
    await client.upload('/issues/1/attachments', form)
    expect(fetchImpl.mock.calls[0][1].headers['Content-Type']).toBeUndefined()
    expect(fetchImpl.mock.calls[0][1].body).toBe(form)
  })

  it('leaves out empty, false and missing query values', async () => {
    const { client, fetchImpl } = setup(() => reply(200, {}))
    await client.get('/staff/issues', { query: { scope: 'team', status: '', overdue: false, limit: 20, offset: 0, x: undefined } })
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/grievance/staff/issues?scope=team&limit=20&offset=0')
  })

  it('returns null for 204', async () => {
    const { client } = setup(() => reply(204))
    expect(await client.post('/x')).toBeNull()
  })
})

describe('errors', () => {
  it('uses the server message and keeps the body', async () => {
    const { client } = setup(() => reply(409, { detail: 'You already have an open ticket.', existing_ticket_id: 'abc' }))
    const err = await client.post('/issues', {}).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.message).toBe('You already have an open ticket.')
    expect(err.data.existing_ticket_id).toBe('abc')
  })

  it('turns validation lists into one sentence', () => {
    expect(detailToMessage([{ msg: 'Value error, Please describe the problem' }, { msg: 'Field required' }]))
      .toBe('Please describe the problem; Field required')
    expect(detailToMessage('plain')).toBe('plain')
    expect(detailToMessage(undefined)).toBeNull()
  })

  it.each([[403, /not allowed/i], [404, /not found/i], [429, /too many/i], [500, /something went wrong/i], [413, /too large/i]])(
    'has a plain message for %i', async (status, pattern) => {
      const { client } = setup(() => reply(status, 'oops', 'text/plain'))
      const err = await client.get('/x').catch((e) => e)
      expect(err.message).toMatch(pattern)
    })

  it('reports an unreachable server as status 0', async () => {
    const { client } = setup(() => Promise.reject(new TypeError('Failed to fetch')))
    const err = await client.get('/x').catch((e) => e)
    expect(err.status).toBe(0)
    expect(err.message).toMatch(/could not reach the server/i)
  })

  it('lets aborts through unchanged', async () => {
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' })
    const { client } = setup(() => Promise.reject(abort))
    await expect(client.get('/x')).rejects.toBe(abort)
  })

  it('calls onUnauthorized for 401 unless the request is silent', async () => {
    const { client } = setup(() => reply(401, { detail: 'Not authenticated' }))
    const fn = vi.fn()
    client.setOnUnauthorized(fn)
    await client.get('/issues/mine').catch(() => {})
    expect(fn).toHaveBeenCalledTimes(1)
    await client.get('/me', { silent401: true }).catch(() => {})
    expect(fn).toHaveBeenCalledTimes(1)
  })
})

describe('endpoints', () => {
  it('remembers the CSRF token from login and forgets it on logout', async () => {
    const calls = []
    const { client } = setup((url, init) => { calls.push([url, init]); return reply(200, url.endsWith('/dev-login') ? { csrf_token: 'T1' } : {}) })
    const api = createApi(client)
    await api.devLogin('ravi@college.edu')
    await api.reply('t1', 'hello')
    expect(calls[1][1].headers['X-CSRF-Token']).toBe('T1')
    await api.logout()
    await api.confirm('t1')
    expect(calls[3][1].headers['X-CSRF-Token']).toBeUndefined()
  })

  it('builds the paths the backend expects', async () => {
    const urls = []
    const { client } = setup((url, init) => { urls.push(`${init.method} ${url}`); return reply(200, {}) })
    const api = createApi(client)
    await api.myIssues({ status: 'CLOSED', limit: 5, offset: 10 })
    await api.staffIssues({ scope: 'team', overdue: true })
    await api.reassign('t 1', 'u1', 'leave')
    await api.markRead('n1')
    expect(urls).toEqual([
      'GET /api/grievance/issues/mine?status=CLOSED&limit=5&offset=10',
      'GET /api/grievance/staff/issues?scope=team&overdue=true&limit=20&offset=0',
      'POST /api/grievance/issues/t%201/reassign',
      'POST /api/grievance/notifications/n1/read',
    ])
    expect(api.attachmentUrl('a/b')).toBe('/api/grievance/attachments/a%2Fb')
  })
})

describe('admin calls', () => {
  it('sends PATCH and DELETE with the CSRF token', async () => {
    const calls = []
    const { client } = setup((url, init) => { calls.push([url, init]); return reply(200, {}) })
    const api = createApi(client)
    client.setCsrf('T')
    await api.adminUpdateRoute('r 1', { level0_user_id: 'u' })
    await api.adminDeleteRoute('r1')
    expect(calls[0][0]).toBe('/api/grievance/admin/routing/r%201')
    expect(calls[0][1]).toMatchObject({ method: 'PATCH', body: '{"level0_user_id":"u"}' })
    expect(calls[1][1]).toMatchObject({ method: 'DELETE' })
    expect(calls.every(([, i]) => i.headers['X-CSRF-Token'] === 'T')).toBe(true)
  })

  it('sends dry_run as the text true or false (false must not be dropped)', async () => {
    const urls = []
    const { client } = setup((url) => { urls.push(url); return reply(200, {}) })
    const api = createApi(client)
    const file = new File(['x'], 'a.csv')
    await api.adminImport('routing', file, true)
    await api.adminImport('users', file, false)
    expect(urls).toEqual(['/api/grievance/admin/routing/import?dry_run=true', '/api/grievance/admin/users/import?dry_run=false'])
  })

  it('reads a CSV template as text', async () => {
    const { client } = setup(() => reply(200, 'a,b\n1,2\n', 'text/csv'))
    expect(await createApi(client).adminTemplate('users')).toBe('a,b\n1,2\n')
  })

  it('filters admin lists with the names the server expects', async () => {
    const urls = []
    const { client } = setup((url) => { urls.push(url); return reply(200, {}) })
    const api = createApi(client)
    await api.adminIssues({ status: 'CLOSED', categoryId: 'c1', overdue: true, q: 'ac', limit: 5, offset: 0 })
    await api.adminUsers({ role: 'staff', active: false, q: 'ra' })
    expect(urls[0]).toBe('/api/grievance/admin/issues?status=CLOSED&category_id=c1&overdue=true&q=ac&limit=5&offset=0')
    expect(urls[1]).toBe('/api/grievance/admin/users?role=staff&active=false&q=ra&limit=50&offset=0')
  })
})
