import { RefreshCw } from 'lucide-react'
import { useApi } from '../../api/ApiContext'
import { DataTable } from '../../components/AdminBits'
import { Alert, Badge, Button, Card, ErrorBox, Spinner } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { useInterval } from '../../hooks/useInterval'
import { formatDateTime } from '../../lib/format'

export default function HealthPage() {
  const api = useApi()
  const { data: h, error, loading, reload } = useAsync(() => api.adminHealth(), [])
  useInterval(reload, 30000)
  if (loading && !h) return <Spinner />
  if (error && !h) return <ErrorBox error={error} onRetry={reload} />

  const w = h.worker
  const worker = {
    ok: ['green', 'Running', null],
    stale: ['red', 'Not running', 'The background worker has not run recently. Escalations, automatic closing and emails are paused. Restart it (see the runbook).'],
    never: ['red', 'Never ran', 'The background worker has never run. Nothing will escalate and no email will be sent until it is started.'],
  }[w.status]

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-white">System health</h2>
        <Button variant="secondary" className="ml-auto" onClick={reload} loading={loading}><RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh</Button>
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}

      <Card className="space-y-2">
        <div className="flex items-center gap-2"><h3 className="font-medium text-white">Background worker</h3><Badge tone={worker[0]}>{worker[1]}</Badge></div>
        {worker[2] && <Alert tone="error">{worker[2]}</Alert>}
        <p className="text-sm text-white/70">
          {w.last_heartbeat ? `Last ran ${w.minutes_ago} minute${w.minutes_ago === 1 ? '' : 's'} ago (${formatDateTime(w.last_heartbeat)}).` : 'No run recorded.'}
          {w.last_run && ` Last pass: ${Object.entries(w.last_run).map(([k, v]) => `${k.replace('_', ' ')} ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ')}.`}
        </p>
        {w.last_error && <Alert tone="warn" title="Last error recorded">{w.last_error}</Alert>}
      </Card>

      <Card className="space-y-2">
        <div className="flex items-center gap-2"><h3 className="font-medium text-white">Email</h3>
          <Badge tone={h.email.configured ? 'green' : 'amber'}>{h.email.configured ? 'Configured' : 'Not configured'}</Badge></div>
        {!h.email.configured && <Alert tone="warn">Email is not set up. Notifications appear inside the system only. Ask IT for SMTP details (see the deployment guide).</Alert>}
        <p className="text-sm text-white/70">{h.email.waiting} waiting to be sent · {h.email.gave_up} gave up after repeated failures.</p>
        {h.email.recent_failures.length > 0 && (
          <DataTable rows={h.email.recent_failures.map((f) => ({ ...f, id: f.notification_id }))} columns={[
            { key: 'to', label: 'To' }, { key: 'error', label: 'Problem' }, { key: 'attempts', label: 'Attempts' },
            { key: 'at', label: 'Created', render: (f) => formatDateTime(f.at) }]} />
        )}
      </Card>

      <Card className="space-y-2">
        <h3 className="font-medium text-white">Checks</h3>
        <p className="text-sm text-white/70">Overdue tickets right now: <strong className={h.overdue_tickets ? 'text-red-300' : ''}>{h.overdue_tickets}</strong></p>
        <ul className="space-y-2">
          <li><Check ok={h.checks.database === 'ok'} label="Database reachable" /></li>
          <li><Check ok={h.checks.uploads_dir_writable} label="Upload folder is writable" bad="Uploads will fail. Check the folder's permissions." /></li>
          <li><Check ok={h.checks.clamav_enabled} warn label="Uploaded files are virus-scanned" bad="Uploaded files are NOT virus-scanned. This is a known limitation unless the server has ClamAV." /></li>
          <li><Check ok={!h.checks.dev_login_enabled} label="Test sign-in is off" bad="Test sign-in is ON. It must be off on the live system." /></li>
          <li><Check ok={h.checks.watchdog_enabled} warn label="Worker watchdog is on" bad="The watchdog that emails you when the worker stops is off." /></li>
        </ul>
      </Card>
    </div>
  )
}

function Check({ ok, label, bad, warn = false }) {
  return ok
    ? <p className="flex items-center gap-2 text-sm text-white/80"><Badge tone="green">OK</Badge> {label}</p>
    : <Alert tone={warn ? 'warn' : 'error'} title={label}>{bad}</Alert>
}
