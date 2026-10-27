import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReportProblemButton, looksLikeAProblem, reportUrl } from './ReportProblemButton'

describe('Report this as a problem', () => {
  it('appears under an answer about something broken', () => {
    render(<ReportProblemButton text="The AC in my room has not been working since Monday" />)
    const link = screen.getByRole('link', { name: /report this as a problem/i })
    expect(link.getAttribute('href')).toMatch(/^\/grievance\/new\?text=/)
    expect(decodeURIComponent(link.getAttribute('href'))).toContain('The AC in my room has not been working since Monday')
  })

  it('stays away from questions that need an explanation, not a ticket', () => {
    render(<ReportProblemButton text="What is the attendance rule for first year students?" />)
    expect(screen.queryByRole('link')).toBeNull()
    expect(looksLikeAProblem('How do I apply for a re-evaluation?')).toBe(false)
  })

  it('can be shown on every answer when the shell asks for it', () => {
    render(<ReportProblemButton text="What is the attendance rule?" always />)
    expect(screen.getByRole('link', { name: /report this as a problem/i })).toBeInTheDocument()
  })

  it('cuts the description to 1000 characters and strips control characters', () => {
    const href = reportUrl(`line\u0000one ${'x'.repeat(1500)}`)
    const text = new URL(href, 'http://localhost').searchParams.get('text')
    expect(text.length).toBe(1000)
    expect(text.startsWith('line one')).toBe(true)
  })

  it('does not create a link for an empty message', () => {
    expect(reportUrl('')).toBe('/grievance/new')
    expect(looksLikeAProblem('')).toBe(false)
  })
})
