import { describe, expect, it } from 'vitest'
import { checkFiles } from '../lib/files'
import { formatDateTime, parseDate, shortText, timeUntil } from '../lib/format'
import { statusInfo } from '../lib/status'
import { navItems } from '../layout/GrievanceLayout'
import { ME } from '../../test/helpers'

const file = (name, type, size = 1000) => new File([new Uint8Array(size)], name, { type })

describe('dates', () => {
  it('treats timestamps without a zone as UTC', () => {
    expect(parseDate('2026-10-08T10:00:00').toISOString()).toBe('2026-10-08T10:00:00.000Z')
    expect(parseDate('2026-10-08T10:00:00+05:30').toISOString()).toBe('2026-10-08T04:30:00.000Z')
    expect(parseDate('nonsense')).toBeNull()
    expect(formatDateTime(null)).toBe('')
  })

  it('says how long is left or how late it is', () => {
    const now = new Date('2026-10-08T12:00:00Z')
    expect(timeUntil('2026-10-08T17:00:00Z', now)).toEqual({ text: 'due in 5 h', overdue: false })
    expect(timeUntil('2026-10-08T11:30:00Z', now)).toEqual({ text: 'overdue by 30 min', overdue: true })
    expect(timeUntil('2026-10-05T12:00:00Z', now).text).toBe('overdue by 3 days')
    expect(timeUntil(null, now).text).toBe('')
  })

  it('shortens long text', () => {
    expect(shortText('a  b\n c')).toBe('a b c')
    expect(shortText('x'.repeat(200), 10)).toHaveLength(10)
  })
})

describe('status wording', () => {
  it('uses plainer words for the person who reported it', () => {
    expect(statusInfo('NEEDS_INFO', { isReporter: true }).label).toBe('Needs your reply')
    expect(statusInfo('NEEDS_INFO').label).toBe('Waiting for reply')
    expect(statusInfo('RESOLVED', { isReporter: true }).label).toMatch(/confirm/i)
    expect(statusInfo('WHATEVER').label).toBe('WHATEVER')
  })
})

describe('file checks', () => {
  it('accepts JPG, PNG and PDF', () => {
    const r = checkFiles([file('a.jpg', 'image/jpeg'), file('b.PNG', 'image/png'), file('c.pdf', 'application/pdf')])
    expect(r.accepted).toHaveLength(3)
    expect(r.errors).toEqual([])
  })

  it('rejects other types, big, empty and too many files', () => {
    const big = file('big.jpg', 'image/jpeg', 11 * 1024 * 1024)
    const r = checkFiles([file('x.exe', 'application/octet-stream'), file('d.docx', 'application/msword'), big, file('e.png', 'image/png', 0)])
    expect(r.accepted).toHaveLength(0)
    expect(r.errors).toHaveLength(4)
    const many = checkFiles([1, 2, 3, 4].map((i) => file(`f${i}.png`, 'image/png')))
    expect(many.accepted).toHaveLength(3)
    expect(many.errors[0]).toMatch(/at most 3/)
    expect(checkFiles([file('g.png', 'image/png')], 3).accepted).toHaveLength(0)       // already has 3
  })

  it('rejects a renamed file whose type does not match', () => {
    expect(checkFiles([file('virus.jpg', 'application/x-msdownload')]).errors).toHaveLength(1)
  })
})

describe('menu', () => {
  const labels = (me) => navItems(me).map((i) => i.label)
  it('shows each person only their own sections', () => {
    expect(labels(ME.student)).toEqual(['My issues', 'Report a problem'])
    expect(labels(ME.staff)).toEqual(['My queue', 'My issues', 'Report a problem'])
    expect(labels(ME.head)).toEqual(['My queue', 'Team', 'Overdue', 'My issues', 'Report a problem'])
    expect(labels(ME.officer)).toContain('Team')
    expect(labels(ME.admin)).toEqual(['My issues', 'Report a problem', 'Admin'])
    expect(labels(null)).toEqual([])
  })
})
