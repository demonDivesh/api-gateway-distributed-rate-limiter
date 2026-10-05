import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchMe, login as loginApi, logoutRequest, tokenStore, type UserInfo } from './api'

interface AuthState {
  user: UserInfo | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    if (!tokenStore.get()) {
      setLoading(false)
      return
    }
    fetchMe()
      .then((u) => active && setUser(u))
      .catch(() => tokenStore.set(null))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const onLogout = () => setUser(null)
    window.addEventListener('gateway:logout', onLogout)
    return () => window.removeEventListener('gateway:logout', onLogout)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    tokenStore.set(await loginApi(username, password))
    setUser(await fetchMe())
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } catch {
      /* token may already be invalid; clear local state regardless */
    }
    tokenStore.set(null)
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
