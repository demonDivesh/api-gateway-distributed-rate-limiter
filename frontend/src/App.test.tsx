import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { AuthProvider } from './auth'

describe('routing', () => {
  beforeEach(() => sessionStorage.clear())

  it('redirects anonymous visitors to the login form', async () => {
    render(
      <MemoryRouter initialEntries={['/playground']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeTruthy()
  })
})
