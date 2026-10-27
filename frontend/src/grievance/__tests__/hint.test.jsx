import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchHint } from '../lib/hint'
import { fakeApi, renderAt } from '../../test/helpers'

vi.mock('../config', async (orig) => ({ ...(await orig()), HINT_URL: 'https://college.test/chat/ask' }))

const ask = (body, ok = true) => vi.fn().mockResolvedValue({ ok, json: async () => body })
const LONG = 'The AC in my hostel room has not worked for two days now'

describe('fetchHint', () => {
  it('is off without a URL', async () => {
    expect(await fetchHint('hello there', { url: '' })).toBeNull()
  })

  it('returns a cleaned answer and safe sources', async () => {
    const f = ask({ answer: '  Check the hostel rules.  ', sources: [
      { title: 'Hostel Rules', section: '4.2', url: 'https://college.test/rules.pdf' },
      { title: 'Bad link', url: 'javascript:alert(1)' }, { nope: true }] })
    const hint = await fetchHint('x', { url: 'https://c/ask', fetchImpl: f })
    expect(f).toHaveBeenCalledWith('https://c/ask', expect.objectContaining({ method: 'POST', credentials: 'include', body: '{"text":"x"}' }))
    expect(hint.answer).toBe('Check the hostel rules.')
    expect(hint.sources).toEqual([
      { title: 'Hostel Rules', section: '4.2', url: 'https://college.test/rules.pdf' },
      { title: 'Bad link', section: '', url: '' }])
  })

  it.each([['empty answer', ask({ answer: '  ' })], ['http error', ask({ answer: 'x' }, false)],
    ['network failure', vi.fn().mockRejectedValue(new TypeError('x'))], ['not json', vi.fn().mockResolvedValue({ ok: true, json: async () => { throw new Error('x') } })]])(
    'returns nothing on %s', async (_n, f) => { expect(await fetchHint('x', { url: 'https://c/ask', fetchImpl: f })).toBeNull() })
})

describe('the hint on the report form', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows the chatbot\'s answer as plain text with a label, and can be hidden', async () => {
    vi.stubGlobal('fetch', ask({ answer: 'Report AC faults to the caretaker.\n<b>Bold?</b>', sources: [{ title: 'Hostel Rules', section: 'Section 3' }] }))
    const { user } = renderAt('/grievance/new', fakeApi())
    await user.type(await screen.findByLabelText(/what is the problem/i), LONG)
    expect(await screen.findByText(/before you submit: this may help/i, {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByText(/Report AC faults/)).toHaveTextContent('<b>Bold?</b>')           // not interpreted as HTML
    expect(screen.getByText(/Source: Hostel Rules, Section 3/)).toBeInTheDocument()
    expect(screen.getByText(/automated suggestion/i)).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('https://college.test/chat/ask', expect.objectContaining({ credentials: 'include' }))
    await user.click(screen.getByRole('button', { name: /hide this suggestion/i }))
    expect(screen.queryByText(/before you submit/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit/i })).toBeEnabled()
  })

  it('never sends sensitive text to the chatbot', async () => {
    const f = ask({ answer: 'x' })
    vi.stubGlobal('fetch', f)
    const api = fakeApi({ classify: vi.fn().mockResolvedValue({ suggested: { id: 'c-conf', name: 'x' }, confidence: 'high', alternatives: [], confidential: true, urgent: false }) })
    const { user } = renderAt('/grievance/new', api)
    await user.type(await screen.findByLabelText(/what is the problem/i), 'Someone has been harassing me near the hostel gate')
    await waitFor(() => expect(api.classify).toHaveBeenCalled(), { timeout: 3000 })
    await new Promise((r) => setTimeout(r, 2000))
    expect(f).not.toHaveBeenCalled()
    expect(screen.queryByText(/before you submit/i)).not.toBeInTheDocument()
  })

  it('does not send the text when it could not be classified', async () => {
    const f = ask({ answer: 'x' })
    vi.stubGlobal('fetch', f)
    const failing = fakeApi({ classify: vi.fn().mockRejectedValue(new Error('down')) })
    const { user } = renderAt('/grievance/new', failing)
    await user.type(await screen.findByLabelText(/what is the problem/i), LONG)
    await new Promise((r) => setTimeout(r, 2200))
    expect(f).not.toHaveBeenCalled()
  })

  it('does not ask for short text and shows nothing when the chatbot fails', async () => {
    const f = vi.fn().mockRejectedValue(new TypeError('down'))
    vi.stubGlobal('fetch', f)
    const { user } = renderAt('/grievance/new', fakeApi())
    await user.type(await screen.findByLabelText(/what is the problem/i), 'short text')
    await new Promise((r) => setTimeout(r, 1800))
    expect(f).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText(/what is the problem/i), ' but now it is much longer than before')
    await waitFor(() => expect(f).toHaveBeenCalled(), { timeout: 4000 })
    expect(screen.queryByText(/before you submit/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
