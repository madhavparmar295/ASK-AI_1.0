// Plain-language names and colours for ticket statuses.
const STATUS = {
  ASSIGNED: { label: 'Waiting for work', tone: 'amber' },
  IN_PROGRESS: { label: 'In progress', tone: 'blue' },
  ESCALATED: { label: 'Escalated', tone: 'orange' },
  NEEDS_INFO: { label: 'Waiting for reply', reporterLabel: 'Needs your reply', tone: 'purple' },
  RESOLVED: { label: 'Resolved', reporterLabel: 'Fixed? Please confirm', tone: 'green' },
  CLOSED: { label: 'Closed', tone: 'slate' },
  CANCELLED: { label: 'Cancelled', tone: 'slate' },
}

export const STATUS_OPTIONS = Object.keys(STATUS)

export function statusInfo(status, { isReporter = false } = {}) {
  const s = STATUS[status] || { label: status || 'Unknown', tone: 'slate' }
  return { label: (isReporter && s.reporterLabel) || s.label, tone: s.tone }
}
