import { afterEach, describe, expect, it, vi } from 'vitest'

// The hint used to require VITE_HINT_URL to exist when the dev server started. That made
// it silently disappear for anyone whose server was already running, which looked exactly
// like "the chatbot is not answering". A missing variable now means the default endpoint.
afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

async function hintUrlWith(value) {
  vi.resetModules()
  if (value === undefined) vi.stubEnv('VITE_HINT_URL', undefined)
  else vi.stubEnv('VITE_HINT_URL', value)
  const { HINT_URL } = await import('../config')
  return HINT_URL
}

describe('the hint endpoint address', () => {
  it('defaults to the endpoint the chatbot serves', async () => {
    expect(await hintUrlWith(undefined)).toBe('/chat/api/ask')
  })

  it('uses an explicit address', async () => {
    expect(await hintUrlWith('/custom/ask')).toBe('/custom/ask')
  })

  it('can be switched off with an empty value', async () => {
    expect(await hintUrlWith('')).toBe('')
  })
})
