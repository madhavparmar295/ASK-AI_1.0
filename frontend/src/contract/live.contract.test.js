// @vitest-environment node
// Runs the real API client against a real backend. Skipped unless BACKEND_URL is set:
//   BACKEND_URL=http://localhost:8000 npm run test:contract
// The backend needs seed data (python -m app.seed) and DEV_LOGIN_ENABLED=true.
import { beforeAll, describe, expect, it } from 'vitest'
import { ApiError, createClient } from '../grievance/api/client'
import { createApi } from '../grievance/api/endpoints'

const BACKEND = process.env.BACKEND_URL
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...Array(64).fill(7)])

/** fetch with a cookie jar, like a browser tab. One jar per signed-in person. */
function browser() {
  const jar = new Map()
  const fetchImpl = async (url, init = {}) => {
    const headers = { ...(init.headers || {}) }
    if (jar.size) headers.Cookie = [...jar].map(([k, v]) => `${k}=${v}`).join('; ')
    const res = await fetch(BACKEND + url, { ...init, headers })
    for (const c of res.headers.getSetCookie?.() || []) {
      const [pair] = c.split(';')
      const i = pair.indexOf('=')
      const name = pair.slice(0, i), value = pair.slice(i + 1)
      if (/max-age=0/i.test(c) || value === '""' || value === '') jar.delete(name); else jar.set(name, value)
    }
    return res
  }
  const api = createApi(createClient({ baseUrl: '/api/grievance', fetchImpl }))
  return { api, jar, fetchImpl }
}

async function signIn(email) {
  const b = browser()
  const me = await b.api.devLogin(email)
  return { ...b, me }
}

describe.skipIf(!BACKEND)('the screens\' API calls against the real backend', () => {
  let ravi, priya, caretaker, warden, officer, admin, options
  let hostelCat, hostelA, confCat

  beforeAll(async () => {
    ;[ravi, priya, caretaker, warden, officer, admin] = await Promise.all(
      ['ravi', 'priya', 'caretaker_a', 'warden', 'officer1', 'admin'].map((k) => signIn(`${k}@college.edu`)))
    options = await ravi.api.formOptions()
    hostelCat = options.categories.find((c) => c.name === 'Hostel and housing')
    confCat = options.categories.find((c) => c.confidential)
    hostelA = options.units.find((u) => u.name === 'Hostel A')
  })

  it('signs in and knows who the person is', async () => {
    expect(ravi.me).toMatchObject({ email: 'ravi@college.edu', role: 'student', hostel: 'Hostel A', is_head: false })
    expect(ravi.me.csrf_token).toBeTruthy()
    expect((await ravi.api.me()).name).toBe('Ravi Kumar')
    expect(warden.me.is_head).toBe(true)
    expect(officer.me.role).toBe('officer')
  })

  it('offers the form its options', () => {
    expect(options.categories.length).toBeGreaterThanOrEqual(12)
    expect(options.categories[0]).toHaveProperty('unit_type')
    expect(hostelCat.unit_type).toBe('hostel')
    expect(options.units.some((u) => u.type === 'hostel')).toBe(true)
  })

  it('suggests a category', async () => {
    const r = await ravi.api.classify('The AC in my hostel room is not working since two days')
    expect(r.suggested.name).toBe('Hostel and housing')
    expect(['high', 'medium', 'low', 'none']).toContain(r.confidence)
    expect(r).toMatchObject({ confidential: false, urgent: false })
    expect((await ravi.api.classify('A senior keeps harassing me')).confidential).toBe(true)
  })

  let ticketId, ticketNo
  it('runs the whole life of a ticket as the screens would', async () => {
    const created = await ravi.api.createIssue({
      description: 'The AC in my room is not working at all', category_id: hostelCat.id, unit_id: hostelA.id,
      location_text: 'A-101', confidential: false })
    ticketId = created.id; ticketNo = created.ticket_no
    expect(created).toMatchObject({ status: 'ASSIGNED', reporter: null, escalation_level: 0 })
    expect(created.assignee.name).toBe('Caretaker Hostel A')
    expect(created.actions).toEqual(expect.arrayContaining(['reply', 'cancel']))

    const att = await ravi.api.uploadAttachment(ticketId, new File([PNG], 'ac.png', { type: 'image/png' }))
    expect(att).toMatchObject({ original_name: 'ac.png', mime_type: 'image/png', uploaded_by_me: true })

    // the caretaker sees it in their queue, with the reporter's details
    const queue = await caretaker.api.staffIssues({ scope: 'mine' })
    expect(queue.items.find((t) => t.id === ticketId)).toMatchObject({ reporter_name: 'Ravi Kumar', overdue: false })
    const asStaff = await caretaker.api.getIssue(ticketId)
    expect(asStaff.reporter).toMatchObject({ name: 'Ravi Kumar', room: 'A-101' })
    expect(asStaff.actions).toEqual(expect.arrayContaining(['start', 'resolve', 'request_info']))
    expect(asStaff.attachments).toHaveLength(1)

    expect((await caretaker.api.start(ticketId)).status).toBe('IN_PROGRESS')
    expect((await caretaker.api.requestInfo(ticketId, 'Which unit is it?')).status).toBe('NEEDS_INFO')
    const mid = await ravi.api.getIssue(ticketId)
    expect(mid.actions).toContain('reply')
    expect((await ravi.api.reply(ticketId, 'The left one')).status).toBe('IN_PROGRESS')
    expect((await caretaker.api.resolve(ticketId, 'Replaced the capacitor')).status).toBe('RESOLVED')

    const resolved = await ravi.api.getIssue(ticketId)
    expect(resolved.actions).toEqual(expect.arrayContaining(['confirm', 'reopen']))
    expect((await ravi.api.confirm(ticketId)).status).toBe('CLOSED')
    expect(await ravi.api.feedback(ticketId, 5, 'Quick')).toMatchObject({ rating: 5, comment: 'Quick' })
    const final = await ravi.api.getIssue(ticketId)
    expect(final.feedback.rating).toBe(5)
    expect(final.events.map((e) => e.to_status).filter(Boolean)).toEqual(
      ['ASSIGNED', 'IN_PROGRESS', 'NEEDS_INFO', 'IN_PROGRESS', 'RESOLVED', 'CLOSED'])
    expect(final.events.every((e) => 'actor' in e && 'created_at' in e && 'text' in e)).toBe(true)
    expect(final.events.some((e) => e.internal)).toBe(false)                 // students never see internal events
  })

  it('lists my issues with paging and a status filter', async () => {
    const all = await ravi.api.myIssues({ limit: 1 })
    expect(all).toMatchObject({ limit: 1, offset: 0 })
    expect(all.total).toBeGreaterThanOrEqual(1)
    expect(all.items[0]).toEqual(expect.objectContaining({ id: expect.any(String), title: expect.any(String), category: expect.any(Object) }))
    const closed = await ravi.api.myIssues({ status: 'CLOSED' })
    expect(closed.items.some((t) => t.id === ticketId)).toBe(true)
    expect((await ravi.api.myIssues({ status: 'ASSIGNED' })).items.some((t) => t.id === ticketId)).toBe(false)
  })

  it('serves the file only to people who may see the ticket', async () => {
    const t = await ravi.api.getIssue(ticketId)
    const url = ravi.api.attachmentUrl(t.attachments[0].id)
    const ok = await ravi.fetchImpl(url)
    expect(ok.status).toBe(200)
    expect(ok.headers.get('content-disposition')).toMatch(/attachment/)
    expect(ok.headers.get('x-content-type-options')).toBe('nosniff')
    expect(new Uint8Array(await ok.arrayBuffer())).toEqual(PNG)
    expect((await priya.fetchImpl(url)).status).toBe(404)
  })

  it('tells the student about a duplicate and keeps the existing ticket id', async () => {
    const body = { description: 'The fan is broken in my room too', category_id: hostelCat.id, unit_id: hostelA.id }
    const first = await ravi.api.createIssue(body)
    const err = await ravi.api.createIssue(body).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.data).toMatchObject({ existing_ticket_id: first.id, existing_ticket_no: first.ticket_no })
    await ravi.api.cancel(first.id, 'Fixed already')
  })

  it('gives plain errors', async () => {
    const short = await ravi.api.createIssue({ description: 'hi', category_id: hostelCat.id }).catch((e) => e)
    expect(short.status).toBe(422)
    expect(short.message).toMatch(/at least 5 characters|describe the problem/i)
    const wrongRole = await ravi.api.staffIssues().catch((e) => e)
    expect(wrongRole.status).toBe(404)
    const nobody = await browser().api.myIssues().catch((e) => e)
    expect(nobody.status).toBe(401)
    const gone = await priya.api.getIssue(ticketId).catch((e) => e)
    expect(gone.status).toBe(404)
    const notAllowed = await warden.api.confirm(ticketId).catch((e) => e)
    expect(notAllowed.status).toBe(403)
  })

  it('refuses changes without the CSRF header', async () => {
    const res = await ravi.fetchImpl('/api/grievance/auth/logout', { method: 'POST' })
    expect(res.status).toBe(403)
    expect((await ravi.api.me()).email).toBe('ravi@college.edu')            // still signed in
  })

  it('escalates and reassigns as a head, using the people the server offers', async () => {
    const t = await ravi.api.createIssue({ description: 'Tap is leaking badly in my room', category_id: hostelCat.id, unit_id: hostelA.id })
    const view = await warden.api.getIssue(t.id)
    expect(view.actions).toEqual(expect.arrayContaining(['escalate', 'reassign']))
    const people = await warden.api.reassignOptions(t.id)
    expect(people.length).toBeGreaterThan(0)
    expect(people[0]).toEqual(expect.objectContaining({ id: expect.any(String), name: expect.any(String), role: expect.any(String) }))
    const careB = people.find((p) => p.name === 'Caretaker Hostel B')
    const moved = await warden.api.reassign(t.id, careB.id, 'Caretaker A on leave')
    expect(moved.assignee.name).toBe('Caretaker Hostel B')
    const up = await warden.api.escalate(t.id, 'No response')
    expect(up).toMatchObject({ status: 'ESCALATED', escalation_level: 1 })
    expect((await warden.api.staffIssues({ scope: 'team' })).items.some((x) => x.id === t.id)).toBe(true)
    expect((await warden.api.staffOverdue()).items.every((x) => x.overdue)).toBe(true)
    const stranger = await caretaker.api.reassignOptions(t.id).catch((e) => e)
    expect([403, 404]).toContain(stranger.status)
  })

  it('keeps confidential tickets away from everybody but the officers', async () => {
    const t = await priya.api.createIssue({ description: 'Someone keeps harassing me near the hostel gate', category_id: confCat.id })
    expect(t).toMatchObject({ confidential: true, assignee: null })
    expect((await officer.api.getIssue(t.id)).reporter.name).toBe('Priya Sharma')
    expect((await officer.api.staffIssues({ scope: 'team' })).items.some((x) => x.id === t.id)).toBe(true)
    for (const who of [admin, warden, ravi]) expect((await who.api.getIssue(t.id).catch((e) => e)).status).toBe(404)
    const mine = await priya.api.notifications()
    expect(mine.items.find((n) => n.ticket_id === t.id).text).toBe('There is an update on your ticket. Log in to view it.')
  })

  it('has notifications that can be read', async () => {
    const before = (await ravi.api.unreadCount()).unread
    expect(before).toBeGreaterThan(0)
    const page = await ravi.api.notifications({ limit: 5 })
    expect(page).toEqual(expect.objectContaining({ total: expect.any(Number), unread: expect.any(Number) }))
    const read = await ravi.api.markRead(page.items[0].id)
    expect(read.read).toBe(true)
    await ravi.api.readAll()
    expect((await ravi.api.unreadCount()).unread).toBe(0)
  })

  it('lets an admin look at the numbers, the tickets, the change log and the health of the system', async () => {
    const stats = await admin.api.adminStats()
    expect(stats.tickets).toEqual(expect.objectContaining({ total: expect.any(Number), open: expect.any(Number), overdue: expect.any(Number), by_status: expect.any(Object) }))
    expect(stats.by_category.some((c) => c.confidential && c.total >= 1)).toBe(true)       // counted ...
    const all = await admin.api.adminIssues({ limit: 100 })
    expect(all.items.some((t) => t.confidential)).toBe(false)                                // ... never listed
    expect((await admin.api.adminIssues({ q: 'zzzz-nothing' })).total).toBe(0)
    const health = await admin.api.adminHealth()
    expect(health.worker.status).toBe('never')                                              // no worker is running in this check
    expect(health).toEqual(expect.objectContaining({ email: expect.any(Object), checks: expect.objectContaining({ uploads_dir_writable: true }) }))
    expect((await ravi.api.adminStats().catch((e) => e)).status).toBe(404)
  })

  it('manages categories, locations and routing like the admin screens do', async () => {
    const cat = await admin.api.adminCreateCategory({ name: 'Sports', confidential: false, sla_hours: 48, unit_type: 'building', keywords: 'cricket:3', active: true })
    expect(cat).toMatchObject({ name: 'Sports', sla_hours: 48 })
    expect((await admin.api.adminCreateCategory({ name: 'sports' }).catch((e) => e)).status).toBe(409)
    expect((await admin.api.adminUpdateCategory(cat.id, { sla_hours: 24, keywords: 'cricket:3, football' })).sla_hours).toBe(24)
    const other = (await admin.api.adminCategories()).find((c) => c.name === 'Other')
    expect((await admin.api.adminUpdateCategory(other.id, { active: false }).catch((e) => e)).status).toBe(409)

    const unit = await admin.api.adminCreateUnit({ name: 'Sports Complex', type: 'building' })
    expect(unit).toMatchObject({ routes: 0, active: true })
    const people = (await admin.api.adminUsers({ role: 'staff', active: true, limit: 200 })).items
    const pick = (email) => people.find((p) => p.email === email).id
    const route = await admin.api.adminCreateRoute({ category_id: cat.id, unit_id: unit.id, level0_user_id: pick('librarian@college.edu'), level1_user_id: pick('registrar@college.edu'), level2_user_id: null })
    expect(route.level0.name).toBe('Librarian')
    expect((await admin.api.adminUpdateRoute(route.id, { level0_user_id: pick('transport@college.edu'), level1_user_id: null, level2_user_id: null })).level1).toBeNull()
    const bad = await admin.api.adminCreateRoute({ category_id: confCat.id, level0_user_id: pick('warden@college.edu') }).catch((e) => e)
    expect(bad.status).toBe(422)
    expect(bad.message).toMatch(/not a designated officer/)
    expect((await admin.api.adminRouting({ categoryId: cat.id })).total).toBe(1)
    await admin.api.adminDeleteRoute(route.id)
    expect((await admin.api.adminRouting({ categoryId: cat.id })).total).toBe(0)
    const log = await admin.api.adminAudit({ entity: 'category' })
    expect(log.items.map((a) => a.action)).toEqual(expect.arrayContaining(['create', 'update']))
  })

  it('imports a routing CSV: the preview saves nothing, apply really saves (dry_run=false must reach the server)', async () => {
    const text = 'category,unit,level0_email,level1_email,level2_email\nLibrary,,transport@college.edu,registrar@college.edu,\nNonsense,,warden@college.edu,,\n'
    const file = () => new File([text], 'routes.csv', { type: 'text/csv' })
    const lib = options.categories.find((c) => c.name === 'Library')
    const level0 = async () => (await admin.api.adminRouting({ categoryId: lib.id })).items[0].level0.email
    const before = await level0()
    const preview = await admin.api.adminImport('routing', file(), true)
    expect(preview).toMatchObject({ dry_run: true, updated: 1, errors: 1 })
    expect(preview.rows.find((r) => r.action === 'error').message).toMatch(/Unknown category/)
    expect(await level0()).toBe(before)
    const applied = await admin.api.adminImport('routing', file(), false)
    expect(applied).toMatchObject({ dry_run: false, updated: 1, errors: 1 })
    expect(await level0()).toBe('transport@college.edu')
    expect(await admin.api.adminTemplate('routing')).toMatch(/^category,unit,level0_email/)
  })

  it('imports users the same way and protects the admin from themselves', async () => {
    const text = 'name,email,role,department,hostel,room\nAsha Nair,asha@college.edu,student,ECE,Hostel B,B-210\nBad,bad@gmail.com,student,,,\n'
    const file = () => new File([text], 'users.csv', { type: 'text/csv' })
    expect(await admin.api.adminImport('users', file(), true)).toMatchObject({ created: 1, errors: 1 })
    expect((await admin.api.adminUsers({ q: 'asha' })).total).toBe(0)
    expect(await admin.api.adminImport('users', file(), false)).toMatchObject({ dry_run: false, created: 1 })
    const asha = (await admin.api.adminUsers({ q: 'asha' })).items[0]
    expect(asha).toMatchObject({ email: 'asha@college.edu', role: 'student', room: 'B-210', active: true })
    const created = await admin.api.adminCreateUser({ name: 'Clerk One', email: 'clerk1@college.edu', role: 'staff', department: null, hostel: null, room: null })
    expect(created.role).toBe('staff')
    const me = (await admin.api.adminUsers({ q: 'admin@college.edu' })).items[0]
    expect((await admin.api.adminUpdateUser(me.id, { active: false }).catch((e) => e)).status).toBe(409)
    const ward = (await admin.api.adminUsers({ q: 'warden@' })).items[0]
    expect((await admin.api.adminUpdateUser(ward.id, { active: false })).warnings[0]).toMatch(/routing row/)
    await admin.api.adminUpdateUser(ward.id, { active: true })
    expect(await admin.api.adminTemplate('users')).toMatch(/^name,email,role/)
  })

  it('signs out', async () => {
    const b = await signIn('aman@college.edu')
    await b.api.logout()
    const err = await b.api.me().catch((e) => e)
    expect(err.status).toBe(401)
  })
})
