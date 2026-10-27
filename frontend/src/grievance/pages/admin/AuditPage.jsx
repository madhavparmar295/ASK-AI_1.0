import { useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { DataTable } from '../../components/AdminBits'
import { Button, ErrorBox, Spinner, inputClass } from '../../components/ui'
import { usePagedList } from '../../hooks/usePagedList'
import { formatDateTime } from '../../lib/format'

const ENTITIES = ['category', 'unit', 'routing', 'user', 'ticket']

/** Who changed what, and when. Settings changes, imports, and automatic deletions. */
export default function AuditPage() {
  const api = useApi()
  const [entity, setEntity] = useState('')
  const list = usePagedList((page) => api.adminAudit({ entity, ...page }), [entity])
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Change log</h2>
        <select aria-label="Filter by kind" value={entity} onChange={(e) => setEntity(e.target.value)} className={`${inputClass} ml-auto !w-auto`}>
          <option value="">Everything</option>{ENTITIES.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
      </div>
      {list.loading ? <Spinner /> : list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : (
        <>
          <DataTable rows={list.items.map((a, i) => ({ ...a, id: i }))} empty="No changes recorded yet." columns={[
            { key: 'at', label: 'When', render: (a) => formatDateTime(a.at) },
            { key: 'actor', label: 'Who' },
            { key: 'action', label: 'Action' },
            { key: 'entity', label: 'Kind' },
            { key: 'detail', label: 'Details', render: (a) => <span className="break-words">{a.detail}</span> },
          ]} />
          {list.hasMore && <div className="text-center"><Button variant="secondary" loading={list.loadingMore} onClick={list.loadMore}>Show more</Button></div>}
        </>
      )}
    </div>
  )
}
