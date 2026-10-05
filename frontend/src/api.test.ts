import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it } from 'vitest'
import { errorMessage, tokenStore } from './api'

describe('tokenStore', () => {
  beforeEach(() => sessionStorage.clear())

  it('round-trips tokens and clears them', () => {
    expect(tokenStore.get()).toBeNull()
    tokenStore.set({ access_token: 'a', refresh_token: 'r', expires_in: 900 })
    expect(tokenStore.get()?.access_token).toBe('a')
    tokenStore.set(null)
    expect(tokenStore.get()).toBeNull()
  })

  it('ignores corrupt storage', () => {
    sessionStorage.setItem('gateway.tokens', '{not json')
    expect(tokenStore.get()).toBeNull()
  })
})

describe('errorMessage', () => {
  it('prefers the gateway error envelope', () => {
    const err = new AxiosError('Request failed')
    err.response = { data: { error: { message: 'Rate limit exceeded' } }, status: 429, statusText: '', headers: {}, config: {} as never }
    expect(errorMessage(err)).toBe('Rate limit exceeded')
  })

  it('falls back to generic messages', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage('weird')).toBe('Unexpected error')
  })
})
