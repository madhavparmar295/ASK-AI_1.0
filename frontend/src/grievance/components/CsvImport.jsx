import { useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { Alert, Badge, Button, Card } from './ui'

function saveText(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url; a.download = name; a.click()
  URL.revokeObjectURL(url)
}

const TONE = { create: 'green', update: 'blue', error: 'red' }

/**
 * Import a CSV in two steps: PREVIEW first (nothing is saved), then APPLY.
 * run(file, dryRun) must return { created, updated, errors, rows: [{ row, action, message }] }.
 */
export function CsvImport({ title, help, templateName, loadTemplate, run, onApplied }) {
  const input = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [done, setDone] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  function choose(e) {
    setFile(e.target.files?.[0] || null)
    setPreview(null); setDone(null); setError(null)       // a new file means a new preview
  }
  async function template() {
    setError(null)
    try { saveText(templateName, await loadTemplate()) } catch (e) { setError(e) }
  }
  async function go(dryRun) {
    setBusy(true); setError(null)
    try {
      const r = await run(file, dryRun)
      if (dryRun) { setPreview(r); setDone(null) } else { setDone(r); setPreview(null); onApplied?.(r) }
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  const shown = done || preview
  const nothingToApply = !preview || preview.created + preview.updated === 0

  return (
    <Card className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-white/60">{title}</h3>
      <p className="text-sm text-white/70">{help}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={template}><Download className="h-4 w-4" aria-hidden="true" /> Download the template</Button>
        <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" aria-label={`${title}: choose a CSV file`} tabIndex={-1} onChange={choose} />
        <Button variant="secondary" onClick={() => input.current?.click()}><Upload className="h-4 w-4" aria-hidden="true" /> {file ? 'Choose another file' : 'Choose a CSV file'}</Button>
        {file && <span className="text-sm text-white/70">{file.name}</span>}
      </div>
      {file && (
        <div className="flex flex-wrap gap-2">
          <Button loading={busy && !preview} disabled={busy} onClick={() => go(true)}>1. Check the file (nothing is saved)</Button>
          <Button variant="secondary" disabled={busy || nothingToApply} onClick={() => go(false)}>2. Save the valid rows</Button>
        </div>
      )}
      {error && <Alert tone="error">{error.message}</Alert>}
      {shown && (
        <div className="space-y-2">
          <Alert tone={shown.errors ? 'warn' : 'success'} title={done ? 'Saved' : 'Preview: nothing has been saved yet'}>
            {shown.created} to add, {shown.updated} to update, {shown.errors} with problems.
            {shown.errors > 0 && ' Rows with problems are skipped. Fix them in the file and check again if you need them.'}
          </Alert>
          <div className="max-h-64 overflow-auto rounded-xl bg-white/5">
            <table className="w-full text-left text-xs text-white/80">
              <thead className="sticky top-0 bg-[#1a0f2e] text-white/60"><tr><th className="p-2">Row</th><th className="p-2">Result</th><th className="p-2">Message</th></tr></thead>
              <tbody>
                {shown.rows.map((r) => (
                  <tr key={r.row} className="border-t border-white/5"><td className="p-2">{r.row}</td><td className="p-2"><Badge tone={TONE[r.action]}>{r.action}</Badge></td><td className="p-2">{r.message}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  )
}
