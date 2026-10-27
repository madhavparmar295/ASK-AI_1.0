import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { ConfirmModal, DataTable, FormModal } from '../../components/AdminBits'
import { CsvImport } from '../../components/CsvImport'
import { Badge, Button, ErrorBox, Field, Spinner, inputClass } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { useAsync } from '../../hooks/useAsync'

function Person({ p }) {
  if (!p) return <span className="text-white/30">–</span>
  return (
    <span title={p.email}>{p.name}{!p.active && <Badge tone="red"> deactivated</Badge>}</span>
  )
}

export default function RoutingPage() {
  const api = useApi()
  const toast = useToast()
  const [categoryId, setCategoryId] = useState('')
  const cats = useAsync(() => api.adminCategories(), [])
  const units = useAsync(() => api.adminUnits(), [])
  const people = useAsync(async () => {
    const [s, o] = await Promise.all([api.adminUsers({ role: 'staff', active: true, limit: 200 }), api.adminUsers({ role: 'officer', active: true, limit: 200 })])
    return [...s.items, ...o.items].sort((a, b) => a.name.localeCompare(b.name))
  }, [])
  const routes = useAsync(() => api.adminRouting({ categoryId }), [categoryId])
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const openNew = () => { setErr(null); setEditing({ category_id: '', unit_id: '', level0: '', level1: '', level2: '' }) }
  const openEdit = (r) => { setErr(null); setEditing({ id: r.id, category: r.category.name, unit: r.unit?.name || 'Default for the whole category', confidential: (cats.data || []).find((c) => c.id === r.category.id)?.confidential, level0: r.level0.id, level1: r.level1?.id || '', level2: r.level2?.id || '' }) }

  const cat = editing && !editing.id ? (cats.data || []).find((c) => c.id === editing.category_id) : null
  const confidential = editing?.id ? editing.confidential : cat?.confidential
  const choices = (people.data || []).filter((p) => !confidential || p.role === 'officer')
  const unitChoices = cat && cat.unit_type !== 'campus' ? (units.data || []).filter((u) => u.type === cat.unit_type && u.active) : []

  async function save() {
    if (!editing.id && !editing.category_id) { setErr(new Error('Please choose a category.')); return }
    if (!editing.level0) { setErr(new Error('Level 0 (the first person) is required.')); return }
    const people3 = { level0_user_id: editing.level0, level1_user_id: editing.level1 || null, level2_user_id: editing.level2 || null }
    setBusy(true); setErr(null)
    try {
      if (editing.id) await api.adminUpdateRoute(editing.id, people3)
      else await api.adminCreateRoute({ category_id: editing.category_id, unit_id: editing.unit_id || null, ...people3 })
      toast('Routing saved'); setEditing(null); routes.reload(); units.reload()
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  async function remove() {
    setBusy(true); setErr(null)
    try { await api.adminDeleteRoute(deleting.id); toast('Routing row deleted'); setDeleting(null); routes.reload(); units.reload() }
    catch (e) { setErr(e) } finally { setBusy(false) }
  }
  const sel = (k) => (e) => setEditing({ ...editing, [k]: e.target.value })
  const personSelect = (k, label, required) => (
    <Field label={label} required={required}>
      {(p) => (
        <select {...p} value={editing[k]} onChange={sel(k)} className={inputClass} disabled={people.loading}>
          <option value="">{required ? 'Choose a person…' : 'Nobody'}</option>
          {choices.map((x) => <option key={x.id} value={x.id}>{x.name} ({x.email})</option>)}
        </select>
      )}
    </Field>
  )

  if (routes.loading && !routes.data) return <Spinner />
  if (routes.error && !routes.data) return <ErrorBox error={routes.error} onRetry={routes.reload} />
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Routing</h2>
        <select aria-label="Filter by category" value={categoryId} onChange={(e) => setCategoryId(e.target.value)} className={`${inputClass} !w-auto`}>
          <option value="">All categories</option>
          {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <Button className="ml-auto" onClick={openNew}><Plus className="h-4 w-4" aria-hidden="true" /> Add a routing row</Button>
      </div>
      <p className="text-sm text-white/60">
        A new ticket goes to <strong>level 0</strong>. If the deadline passes it moves to level 1, then level 2. The row for the exact
        location is used first; if there is none, the category's default row; if there is none, the "Other" category.
      </p>
      <DataTable rows={routes.data.items} empty="No routing rows for this category yet." columns={[
        { key: 'category', label: 'Category', render: (r) => r.category.name },
        { key: 'unit', label: 'Location', render: (r) => r.unit?.name || <span className="text-white/50">Default</span> },
        { key: 'l0', label: 'Level 0', render: (r) => <Person p={r.level0} /> },
        { key: 'l1', label: 'Level 1', render: (r) => <Person p={r.level1} /> },
        { key: 'l2', label: 'Level 2', render: (r) => <Person p={r.level2} /> },
        { key: 'a', label: '', render: (r) => (
          <span className="flex gap-1">
            <Button variant="ghost" onClick={() => openEdit(r)} aria-label={`Edit ${r.category.name} ${r.unit?.name || 'default'}`}>Edit</Button>
            <Button variant="ghost" onClick={() => { setErr(null); setDeleting(r) }} aria-label={`Delete ${r.category.name} ${r.unit?.name || 'default'}`}>Delete</Button>
          </span>) },
      ]} />

      {editing && (
        <FormModal open title={editing.id ? 'Edit routing row' : 'Add a routing row'} onClose={() => setEditing(null)} onSubmit={save} busy={busy} error={err}>
          {editing.id ? (
            <p className="text-sm text-white/80"><strong>{editing.category}</strong> · {editing.unit}</p>
          ) : (
            <>
              <Field label="Category" required>
                {(p) => <select {...p} value={editing.category_id} onChange={(e) => setEditing({ ...editing, category_id: e.target.value, unit_id: '' })} className={inputClass}>
                  <option value="">Choose a category…</option>{(cats.data || []).filter((c) => c.active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}
              </Field>
              {unitChoices.length > 0 && (
                <Field label="Location" hint="Leave on 'Default' to cover every location without its own row.">
                  {(p) => <select {...p} value={editing.unit_id} onChange={sel('unit_id')} className={inputClass}>
                    <option value="">Default for this category</option>{unitChoices.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>}
                </Field>
              )}
            </>
          )}
          {confidential && <p className="text-xs text-purple-200">This category is confidential: only designated officers can be chosen.</p>}
          {personSelect('level0', 'Level 0: first person', true)}
          {personSelect('level1', 'Level 1: when the deadline passes')}
          {personSelect('level2', 'Level 2: when it passes again')}
        </FormModal>
      )}
      <ConfirmModal open={!!deleting} title="Delete this routing row?" busy={busy} error={err} confirmLabel="Delete"
        message={deleting ? `${deleting.category.name} · ${deleting.unit?.name || 'Default'}. Tickets that already use it block the deletion; change its people instead.` : ''}
        onConfirm={remove} onClose={() => setDeleting(null)} />

      <CsvImport title="Import routing from a CSV file" templateName="routing-template.csv"
        help="One row per category and location. Leave the location empty for the category's default row. People are identified by their college email. Existing rows are updated."
        loadTemplate={() => api.adminTemplate('routing')} run={(file, dry) => api.adminImport('routing', file, dry)}
        onApplied={() => { routes.reload(); units.reload() }} />
    </div>
  )
}
