import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { useAuth } from '../../auth/AuthContext'
import { DataTable, FormModal } from '../../components/AdminBits'
import { CsvImport } from '../../components/CsvImport'
import { Alert, Badge, Button, ErrorBox, Field, Spinner, inputClass } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useDebounce } from '../../hooks/useDebounce'
import { usePagedList } from '../../hooks/usePagedList'

const ROLES = { student: 'Student', staff: 'Staff (handles tickets)', officer: 'Designated officer (confidential tickets)', admin: 'Admin' }
const BLANK = { name: '', email: '', role: 'student', department: '', hostel: '', room: '' }
const tone = { student: 'slate', staff: 'blue', officer: 'purple', admin: 'orange' }

export default function UsersPage() {
  const api = useApi()
  const toast = useToast()
  const { me } = useAuth()
  const [role, setRole] = useState('')
  const [active, setActive] = useState('')
  const [q, setQ] = useState('')
  const search = useDebounce(q.trim(), 500)
  const list = usePagedList((page) => api.adminUsers({ role, active: active === '' ? undefined : active === 'true', q: search, ...page }), [role, active, search])
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [notice, setNotice] = useState([])

  const open = (u) => { setErr(null); setEditing(u ? { ...u, department: u.department || '', hostel: u.hostel || '', room: u.room || '' } : { ...BLANK }) }
  const set = (k) => (e) => setEditing({ ...editing, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function save() {
    const clean = (v) => (v && v.trim() ? v.trim() : null)
    if (!editing.name.trim()) { setErr(new Error('Please enter a name.')); return }
    setBusy(true); setErr(null)
    try {
      if (editing.id) {
        const r = await api.adminUpdateUser(editing.id, { name: editing.name.trim(), role: editing.role, department: clean(editing.department), hostel: clean(editing.hostel), room: clean(editing.room), active: editing.active })
        setNotice(r.warnings || [])
      } else {
        if (!editing.email.trim()) { setErr(new Error('Please enter the college email.')); setBusy(false); return }
        await api.adminCreateUser({ name: editing.name.trim(), email: editing.email.trim(), role: editing.role, department: clean(editing.department), hostel: clean(editing.hostel), room: clean(editing.room) })
        setNotice([])
      }
      toast(editing.id ? 'User saved' : 'User added'); setEditing(null); list.reload()
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Users</h2>
        <input aria-label="Search users" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} className={`${inputClass} !w-56`} />
        <select aria-label="Filter by role" value={role} onChange={(e) => setRole(e.target.value)} className={`${inputClass} !w-auto`}>
          <option value="">All roles</option>{Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select aria-label="Filter by status" value={active} onChange={(e) => setActive(e.target.value)} className={`${inputClass} !w-auto`}>
          <option value="">Active and deactivated</option><option value="true">Active</option><option value="false">Deactivated</option>
        </select>
        <Button className="ml-auto" onClick={() => open(null)}><Plus className="h-4 w-4" aria-hidden="true" /> Add a user</Button>
      </div>
      {notice.map((n) => <Alert key={n} tone="warn">{n}</Alert>)}

      {list.loading ? <Spinner /> : list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : (
        <>
          <p className="text-sm text-white/50">{list.total} user{list.total === 1 ? '' : 's'}</p>
          <DataTable rows={list.items} empty="No users match." columns={[
            { key: 'name', label: 'Name', render: (u) => <span>{u.name}<span className="block text-xs text-white/50">{u.email}</span></span> },
            { key: 'role', label: 'Role', render: (u) => <Badge tone={tone[u.role]}>{ROLES[u.role].split(' (')[0]}</Badge> },
            { key: 'where', label: 'Department / hostel', render: (u) => [u.department, u.hostel, u.room].filter(Boolean).join(' · ') || '–' },
            { key: 'in_routes', label: 'In routing rows' },
            { key: 'active', label: 'Status', render: (u) => <Badge tone={u.active ? 'green' : 'slate'}>{u.active ? 'Active' : 'Deactivated'}</Badge> },
            { key: 'e', label: '', render: (u) => <Button variant="ghost" onClick={() => open(u)} aria-label={`Edit ${u.name}`}>Edit</Button> },
          ]} />
          {list.hasMore && <div className="text-center"><Button variant="secondary" loading={list.loadingMore} onClick={list.loadMore}>Show more</Button></div>}
        </>
      )}

      {editing && (
        <FormModal open title={editing.id ? 'Edit user' : 'Add a user'} onClose={() => setEditing(null)} onSubmit={save} busy={busy} error={err}>
          <Field label="Name" required>{(p) => <input {...p} value={editing.name} maxLength={200} onChange={set('name')} className={inputClass} />}</Field>
          <Field label="College email" required hint={editing.id ? 'The email cannot be changed.' : 'Must be a college Google account.'}>
            {(p) => <input {...p} type="email" value={editing.email} disabled={!!editing.id} maxLength={320} onChange={set('email')} className={inputClass} />}
          </Field>
          <Field label="Role" hint={editing.id && editing.id === me?.id ? 'You cannot change your own role.' : undefined}>
            {(p) => <select {...p} value={editing.role} onChange={set('role')} className={inputClass} disabled={editing.id === me?.id}>{Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Department">{(p) => <input {...p} value={editing.department} maxLength={100} onChange={set('department')} className={inputClass} />}</Field>
            <Field label="Hostel">{(p) => <input {...p} value={editing.hostel} maxLength={100} onChange={set('hostel')} className={inputClass} />}</Field>
            <Field label="Room">{(p) => <input {...p} value={editing.room} maxLength={50} onChange={set('room')} className={inputClass} />}</Field>
          </div>
          {editing.id && (
            <label className="flex items-center gap-3 text-sm text-white/90">
              <input type="checkbox" className="h-4 w-4 accent-purple-500" checked={editing.active} disabled={editing.id === me?.id} onChange={set('active')} />
              Active (a deactivated person cannot sign in and is skipped in routing)
            </label>
          )}
        </FormModal>
      )}

      <CsvImport title="Import users from a CSV file" templateName="users-template.csv"
        help="Columns: name, email, role, department, hostel, room. Existing people (same email) are updated; their active status is kept. Hostel and department names should match the location names so the report form can preselect them."
        loadTemplate={() => api.adminTemplate('users')} run={(file, dry) => api.adminImport('users', file, dry)} onApplied={() => list.reload()} />
    </div>
  )
}
