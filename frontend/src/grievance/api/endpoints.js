import { createClient } from './client'

/** Every call the screens make, in one place. Mirrors docs/CONTRACT.md in the backend. */
export function createApi(client = createClient()) {
  const { get, post, upload, patch, del } = client
  const remember = (data) => { if (data && data.csrf_token) client.setCsrf(data.csrf_token); return data }
  const enc = encodeURIComponent

  return {
    client,
    attachmentUrl: (id) => `${client.baseUrl}/attachments/${enc(id)}`,

    // session
    me: () => get('/me', { silent401: true }).then(remember),
    devUsers: () => get('/auth/dev-users', { silent401: true }),
    devLogin: (email) => post('/auth/dev-login', { email }, { silent401: true }).then(remember),
    googleLogin: (credential) => post('/auth/google', { credential }, { silent401: true }).then(remember),
    logout: () => post('/auth/logout', undefined).finally(() => client.setCsrf(null)),

    // student
    formOptions: () => get('/meta/form-options'),
    classify: (text, signal) => post('/classify', { text }, { signal }),
    createIssue: (payload) => post('/issues', payload),
    myIssues: ({ status, limit = 20, offset = 0 } = {}) => get('/issues/mine', { query: { status, limit, offset } }),
    getIssue: (id) => get(`/issues/${enc(id)}`),
    uploadAttachment: (id, file) => { const f = new FormData(); f.append('file', file); return upload(`/issues/${enc(id)}/attachments`, f) },
    reply: (id, text) => post(`/issues/${enc(id)}/reply`, { text }),
    cancel: (id, reason) => post(`/issues/${enc(id)}/cancel`, reason ? { reason } : {}),
    confirm: (id) => post(`/issues/${enc(id)}/confirm`),
    reopen: (id, reason) => post(`/issues/${enc(id)}/reopen`, { reason }),
    feedback: (id, rating, comment) => post(`/issues/${enc(id)}/feedback`, { rating, comment: comment || null }),

    // staff
    staffIssues: ({ scope = 'mine', status, overdue, limit = 20, offset = 0 } = {}) =>
      get('/staff/issues', { query: { scope, status, overdue, limit, offset } }),
    staffOverdue: ({ limit = 20, offset = 0 } = {}) => get('/staff/overdue', { query: { limit, offset } }),
    start: (id) => post(`/issues/${enc(id)}/start`),
    requestInfo: (id, text) => post(`/issues/${enc(id)}/request-info`, { text }),
    resolve: (id, note) => post(`/issues/${enc(id)}/resolve`, { note }),
    escalate: (id, reason) => post(`/issues/${enc(id)}/escalate`, { reason }),
    reassign: (id, assigneeId, reason) => post(`/issues/${enc(id)}/reassign`, { assignee_id: assigneeId, reason }),
    reassignOptions: (id) => get(`/issues/${enc(id)}/reassign-options`),

    // admin
    adminStats: () => get('/admin/stats'),
    adminIssues: ({ status, categoryId, overdue, q, limit = 20, offset = 0 } = {}) =>
      get('/admin/issues', { query: { status, category_id: categoryId, overdue, q, limit, offset } }),
    adminCategories: () => get('/admin/categories'),
    adminCreateCategory: (body) => post('/admin/categories', body),
    adminUpdateCategory: (id, body) => patch(`/admin/categories/${enc(id)}`, body),
    adminUnits: () => get('/admin/units'),
    adminCreateUnit: (body) => post('/admin/units', body),
    adminUpdateUnit: (id, body) => patch(`/admin/units/${enc(id)}`, body),
    adminRouting: ({ categoryId, limit = 200, offset = 0 } = {}) =>
      get('/admin/routing', { query: { category_id: categoryId, limit, offset } }),
    adminCreateRoute: (body) => post('/admin/routing', body),
    adminUpdateRoute: (id, body) => patch(`/admin/routing/${enc(id)}`, body),
    adminDeleteRoute: (id) => del(`/admin/routing/${enc(id)}`),
    adminUsers: ({ role, active, q, limit = 50, offset = 0 } = {}) =>
      get('/admin/users', { query: { role, active: active === undefined ? undefined : String(active), q, limit, offset } }),
    adminCreateUser: (body) => post('/admin/users', body),
    adminUpdateUser: (id, body) => patch(`/admin/users/${enc(id)}`, body),
    adminTemplate: (kind) => get(`/admin/${kind}/template`),          // kind: 'routing' | 'users'
    // The server's default is a preview. 'false' must be sent as text, or it is dropped from the address.
    adminImport: (kind, file, dryRun) => {
      const f = new FormData(); f.append('file', file)
      return upload(`/admin/${kind}/import`, f, { query: { dry_run: dryRun ? 'true' : 'false' } })
    },
    adminAudit: ({ entity, limit = 50, offset = 0 } = {}) => get('/admin/audit', { query: { entity, limit, offset } }),
    adminHealth: () => get('/admin/health'),

    // notifications
    notifications: ({ unreadOnly, limit = 20, offset = 0 } = {}) =>
      get('/notifications', { query: { unread_only: unreadOnly, limit, offset } }),
    unreadCount: () => get('/notifications/unread-count'),
    markRead: (id) => post(`/notifications/${enc(id)}/read`),
    readAll: () => post('/notifications/read-all'),
  }
}
