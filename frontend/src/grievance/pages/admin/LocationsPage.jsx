import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { DataTable, FormModal } from '../../components/AdminBits'
import { Badge, Button, ErrorBox, Field, Spinner, inputClass } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useAsync } from '../../hooks/useAsync'
import { LOCATION_TYPES } from './CategoriesPage'

const TYPES = Object.entries(LOCATION_TYPES).filter(([k]) => k !== 'campus')

export default function LocationsPage() {
  const api = useApi()
  const toast = useToast()
  const { data, error, loading, reload } = useAsync(() => api.adminUnits(), [])
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [saveError, setSaveError] = useState(null)

  async function save() {
    if (!editing.name.trim()) { setSaveError(new Error('Please enter a name.')); return }
    setBusy(true); setSaveError(null)
    try {
      if (editing.id) await api.adminUpdateUnit(editing.id, { name: editing.name, active: editing.active })
      else await api.adminCreateUnit({ name: editing.name, type: editing.type })
      toast(editing.id ? 'Location saved' : 'Location added')
      setEditing(null); reload()
    } catch (e) { setSaveError(e) } finally { setBusy(false) }
  }
  const open = (row) => { setSaveError(null); setEditing(row ? { ...row } : { name: '', type: 'hostel', active: true }) }

  if (loading && !data) return <Spinner />
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Locations</h2>
        <Button className="ml-auto" onClick={() => open(null)}><Plus className="h-4 w-4" aria-hidden="true" /> Add a location</Button>
      </div>
      <p className="text-sm text-white/60">Hostels, departments, buildings and mess halls. Add a new one here, then give it a routing row.</p>
      <DataTable rows={data} columns={[
        { key: 'type', label: 'Kind', render: (r) => LOCATION_TYPES[r.type] },
        { key: 'name', label: 'Name' },
        { key: 'routes', label: 'Routing rows' },
        { key: 'active', label: 'Status', render: (r) => <Badge tone={r.active ? 'green' : 'slate'}>{r.active ? 'Active' : 'Switched off'}</Badge> },
        { key: 'edit', label: '', render: (r) => <Button variant="ghost" onClick={() => open(r)} aria-label={`Edit ${r.name}`}>Edit</Button> },
      ]} />
      {editing && (
        <FormModal open title={editing.id ? 'Edit location' : 'Add a location'} onClose={() => setEditing(null)} onSubmit={save} busy={busy} error={saveError}>
          {!editing.id && (
            <Field label="Kind" required>{(p) => <select {...p} value={editing.type} onChange={(e) => setEditing({ ...editing, type: e.target.value })} className={inputClass}>{TYPES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}</Field>
          )}
          <Field label="Name" required>{(p) => <input {...p} value={editing.name} maxLength={150} onChange={(e) => setEditing({ ...editing, name: e.target.value })} className={inputClass} />}</Field>
          {editing.id && (
            <label className="flex items-center gap-3 text-sm text-white/90">
              <input type="checkbox" className="h-4 w-4 accent-purple-500" checked={editing.active} onChange={(e) => setEditing({ ...editing, active: e.target.checked })} /> Active (students can choose it)
            </label>
          )}
        </FormModal>
      )}
    </div>
  )
}
