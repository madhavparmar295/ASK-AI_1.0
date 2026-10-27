import { Alert, Button, Modal } from './ui'

/** Plain table for admin lists. columns: [{ key, label, render?(row) }] */
export function DataTable({ columns, rows, empty = 'Nothing here yet.' }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-white/60">{empty}</p>
  return (
    <div className="overflow-x-auto rounded-2xl border border-white/10">
      <table className="w-full min-w-[32rem] text-left text-sm text-white/90">
        <thead className="bg-white/5 text-xs uppercase tracking-wide text-white/60">
          <tr>{columns.map((c) => <th key={c.key} className="px-3 py-2 font-medium">{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-white/5 hover:bg-white/5">
              {columns.map((c) => <td key={c.key} className="px-3 py-2 align-top">{c.render ? c.render(r) : r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** A modal with a form: Save and Close buttons, and the server's error shown inside. */
export function FormModal({ open, title, onClose, onSubmit, busy, error, warnings = [], submitLabel = 'Save', children }) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onSubmit() }} className="space-y-3" noValidate>
        {children}
        {error && <Alert tone="error">{error.message}</Alert>}
        {warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Close</Button>
          <Button type="submit" loading={busy}>{submitLabel}</Button>
        </div>
      </form>
    </Modal>
  )
}

export function ConfirmModal({ open, title, message, confirmLabel, onConfirm, onClose, busy, error }) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <p className="mb-3 text-sm text-white/80">{message}</p>
      {error && <Alert tone="error" className="mb-3">{error.message}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Keep it</Button>
        <Button variant="danger" loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </Modal>
  )
}
