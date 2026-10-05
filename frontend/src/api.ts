import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

export interface TokenPair {
  access_token: string
  refresh_token: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  role: string
  created_at: string
}

export interface UpstreamInstance {
  url: string
  healthy: boolean
  active_connections: number
  circuit_breaker: { state: 'closed' | 'open' | 'half_open'; failures: number }
  last_latency_ms: number | null
  last_error: string | null
  total_requests: number
}

export interface Summary {
  uptime_seconds: number
  total_requests: number
  status_classes: Record<string, number>
  rate_limit: { allowed: number; limited: number; errors: number }
  latency_ms: { p50: number; p95: number; p99: number; samples: number }
  upstreams: { name: string; strategy: string; instances: UpstreamInstance[] }[]
  rate_limit_config: Record<string, number | string>
}

const STORE_KEY = 'gateway.tokens'

export const tokenStore = {
  get(): TokenPair | null {
    try {
      const raw = sessionStorage.getItem(STORE_KEY)
      return raw ? (JSON.parse(raw) as TokenPair) : null
    } catch {
      return null
    }
  },
  set(tokens: TokenPair | null) {
    if (tokens) sessionStorage.setItem(STORE_KEY, JSON.stringify(tokens))
    else sessionStorage.removeItem(STORE_KEY)
  },
}

export const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? '', timeout: 15000 })

api.interceptors.request.use((config) => {
  const tokens = tokenStore.get()
  if (tokens && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${tokens.access_token}`
  }
  return config
})

let refreshing: Promise<TokenPair | null> | null = null

async function refreshTokens(): Promise<TokenPair | null> {
  const current = tokenStore.get()
  if (!current) return null
  try {
    const { data } = await axios.post<TokenPair>(`${api.defaults.baseURL ?? ''}/api/v1/auth/refresh`, {
      refresh_token: current.refresh_token,
    })
    tokenStore.set(data)
    return data
  } catch {
    tokenStore.set(null)
    return null
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined
    const isAuthCall = original?.url?.includes('/api/v1/auth/')
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true
      refreshing ??= refreshTokens().finally(() => {
        refreshing = null
      })
      const fresh = await refreshing
      if (fresh) {
        original.headers = { ...original.headers, Authorization: `Bearer ${fresh.access_token}` }
        return api(original)
      }
      window.dispatchEvent(new Event('gateway:logout'))
    }
    return Promise.reject(error)
  },
)

export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const body = err.response?.data as { error?: { message?: string } } | undefined
    return body?.error?.message ?? err.message
  }
  return err instanceof Error ? err.message : 'Unexpected error'
}

export const login = async (username: string, password: string) =>
  (await api.post<TokenPair>('/api/v1/auth/login', { username, password })).data

export const register = async (username: string, password: string) =>
  (await api.post<UserInfo>('/api/v1/auth/register', { username, password })).data

export const fetchMe = async () => (await api.get<UserInfo>('/api/v1/auth/me')).data
export const fetchSummary = async () => (await api.get<Summary>('/api/v1/metrics/summary')).data
export const logoutRequest = async () => {
  const tokens = tokenStore.get()
  await api.post('/api/v1/auth/logout', { refresh_token: tokens?.refresh_token ?? null })
}
