import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { DataTable, FormModal } from '../../components/AdminBits'
import { Badge, Button, ErrorBox, Field, Spinner, inputClass } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useAsync } from '../../hooks/useAsync'

export const LOCATION_TYPES = { campus: 'None (whole campus)', hostel: 'Hostel', department: 'Department', building: 'Building', mess: 'Mess' }
const EMPTY = { name: '', confidential: false, sla_hours: 72, unit_type: 'campus', keywords: '', active: true }

export default function CategoriesPage() {
  const api = useApi()
  const toast = useToast()
  const { data, error, loading, reload } = useAsync(() => api.adminCategories(), [])
  const [editing, setEditing] = useState(null)        // null | { id?, ...fields }
  const [busy, setBusy] = useState(false)
  const [saveError, setSaveError] = useState(null)

  async function save() {
    const { id, ...body } = editing
    body.sla_hours = Number(body.sla_hours)
    if (!body.name.trim()) { setSaveError(new Error('Please enter a name.')); return }
    if (!(body.sla_hours >= 1)) { setSaveError(new Error('The deadline must be at least 1 hour.')); return }
    setBusy(true); setSaveError(null)
    try {
      if (id) await api.adminUpdateCategory(id, body); else await api.adminCreateCategory(body)
      toast(id ? 'Category saved' : 'Category added')
      setEditing(null); reload()
    } catch (e) { setSaveError(e) } finally { setBusy(false) }
  }
  const set = (k) => (e) => setEditing({ ...editing, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const open = (row) => { setSaveError(null); setEditing(row ? { ...row, keywords: row.keywords || '' } : { ...EMPTY }) }

  if (loading && !data) return <Spinner />
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Categories</h2>
        <Button className="ml-auto" onClick={() => open(null)}><Plus className="h-4 w-4" aria-hidden="true" /> Add a category</Button>
      </div>
      <p className="text-sm text-white/60">Each category has a deadline. When a ticket is not handled in that time it moves to the next person in its routing row.</p>
      <DataTable rows={data} columns={[
        { key: 'name', label: 'Category' },
        { key: 'confidential', label: 'Confidential', render: (r) => (r.confidential ? <Badge tone="purple">Confidential</Badge> : '') },
        { key: 'sla_hours', label: 'Deadline', render: (r) => `${r.sla_hours} h` },
        { key: 'unit_type', label: 'Asks for', render: (r) => LOCATION_TYPES[r.unit_type] },
        { key: 'active', label: 'Status', render: (r) => <Badge tone={r.active ? 'green' : 'slate'}>{r.active ? 'Active' : 'Switched off'}</Badge> },
        { key: 'edit', label: '', render: (r) => <Button variant="ghost" onClick={() => open(r)} aria-label={`Edit ${r.name}`}>Edit</Button> },
      ]} />
      {editing && (
        <FormModal open title={editing.id ? 'Edit category' : 'Add a category'} onClose={() => setEditing(null)} onSubmit={save} busy={busy} error={saveError}>
          <Field label="Name" required>{(p) => <input {...p} value={editing.name} onChange={set('name')} maxLength={150} className={inputClass} />}</Field>
          <Field label="Deadline in hours" required hint="After this time without a fix, the ticket moves up one level.">
            {(p) => <input {...p} type="number" min="1" max="2160" value={editing.sla_hours} onChange={set('sla_hours')} className={inputClass} />}
          </Field>
          <Field label="Which location does the form ask for?" hint="For example Hostel for hostel problems. Routing can then differ per hostel.">
            {(p) => <select {...p} value={editing.unit_type} onChange={set('unit_type')} className={inputClass}>{Object.entries(LOCATION_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}
          </Field>
          <Field label="Words that suggest this category" hint='Separate with commas. "hostel:3" makes a word count more, "leak*" matches leak, leaking, leakage. Spelling variants in Hinglish are welcome.'>
            {(p) => <textarea {...p} rows={4} maxLength={5000} value={editing.keywords} onChange={set('keywords')} className={inputClass} />}
          </Field>
          <label className="flex items-start gap-3 text-sm text-white/90">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-purple-500" checked={editing.confidential} onChange={set('confidential')} />
            <span>Confidential: only designated officers see these tickets. Its routing row may contain officers only.</span>
          </label>
          <label className="flex items-center gap-3 text-sm text-white/90">
            <input type="checkbox" className="h-4 w-4 accent-purple-500" checked={editing.active} onChange={set('active')} /> Active (students can choose it)
          </label>
        </FormModal>
      )}
    </div>
  )
}
