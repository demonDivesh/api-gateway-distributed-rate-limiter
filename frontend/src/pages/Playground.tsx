import { useState, type FormEvent } from 'react'
import { api } from '../api'

interface Result {
  n: number
  status: number
  ms: number
  remaining: string
  limit: string
  instance: string
  requestId: string
  retryAfter: string
  body: string
}

const PRESETS = [
  { label: 'Who am I (Service A)', method: 'GET', path: '/api/service-a/whoami', body: '' },
  { label: 'List items (Service A)', method: 'GET', path: '/api/service-a/items', body: '' },
  {
    label: 'Create item (Service A)',
    method: 'POST',
    path: '/api/service-a/items',
    body: '{"name":"Demo widget","description":"created from the playground","price_cents":1250,"stock":25}',
  },
  { label: 'Create order (Service B)', method: 'POST', path: '/api/service-b/orders', body: '{"item_id":1,"quantity":1}' },
  { label: 'List orders (Service B)', method: 'GET', path: '/api/service-b/orders', body: '' },
]

export default function Playground() {
  const [method, setMethod] = useState('GET')
  const [path, setPath] = useState('/api/service-a/whoami')
  const [body, setBody] = useState('')
  const [count, setCount] = useState(1)
  const [results, setResults] = useState<Result[]>([])
  const [busy, setBusy] = useState(false)
  const [jsonError, setJsonError] = useState<string | null>(null)

  const run = async (e: FormEvent) => {
    e.preventDefault()
    let data: unknown = undefined
    if (body.trim()) {
      try {
        data = JSON.parse(body)
      } catch {
        setJsonError('Request body is not valid JSON')
        return
      }
    }
    setJsonError(null)
    setBusy(true)
    const started = Array.from({ length: count }, async (_, idx): Promise<Result> => {
      const t0 = performance.now()
      const res = await api.request({ method, url: path, data, validateStatus: () => true }).catch((err) => ({
        status: 0,
        headers: {} as Record<string, string>,
        data: String(err),
      }))
      const h = res.headers as Record<string, string>
      return {
        n: idx + 1,
        status: res.status,
        ms: Math.round(performance.now() - t0),
        remaining: h['x-ratelimit-remaining'] ?? '—',
        limit: h['x-ratelimit-limit'] ?? '—',
        instance: h['x-instance-id'] ?? '—',
        requestId: h['x-request-id'] ?? '—',
        retryAfter: h['retry-after'] ?? '',
        body: typeof res.data === 'string' ? res.data : JSON.stringify(res.data),
      }
    })
    setResults(await Promise.all(started))
    setBusy(false)
  }

  const counts = results.reduce<Record<number, number>>((acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }), {})

  return (
    <>
      <h1>Playground</h1>
      <form className="card" onSubmit={run}>
        <div className="presets">
          {PRESETS.map((p) => (
            <button type="button" className="chip" key={p.label} onClick={() => { setMethod(p.method); setPath(p.path); setBody(p.body) }}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="row">
          <select value={method} onChange={(e) => setMethod(e.target.value)} aria-label="HTTP method">
            {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => <option key={m}>{m}</option>)}
          </select>
          <input className="grow" value={path} onChange={(e) => setPath(e.target.value)} aria-label="Path" />
          <label className="inline">
            Repeat ×
            <input type="number" min={1} max={200} value={count} onChange={(e) => setCount(Math.max(1, Math.min(200, Number(e.target.value) || 1)))} />
          </label>
          <button className="btn" disabled={busy}>{busy ? 'Sending…' : 'Send'}</button>
        </div>
        <textarea rows={3} placeholder="JSON body (optional)" value={body} onChange={(e) => setBody(e.target.value)} />
        {jsonError && <div className="alert">{jsonError}</div>}
        <p className="muted small">Set “Repeat” above your rate limit to watch requests turn into 429s. Load balancing is visible in the Instance column.</p>
      </form>

      {results.length > 0 && (
        <section className="card">
          <h2>Results</h2>
          <p className="muted">{Object.entries(counts).map(([s, c]) => `${s}: ${c}`).join('  ·  ')}</p>
          <div className="scroll">
            <table>
              <thead><tr><th>#</th><th>Status</th><th>ms</th><th>Rate limit</th><th>Instance</th><th>Request ID</th><th>Response</th></tr></thead>
              <tbody>
                {results.slice(0, 100).map((r) => (
                  <tr key={r.n}>
                    <td>{r.n}</td>
                    <td><span className={`pill ${r.status >= 200 && r.status < 300 ? 'ok' : r.status === 429 ? 'warn' : 'bad'}`}>{r.status || 'ERR'}</span></td>
                    <td>{r.ms}</td>
                    <td>{r.remaining}/{r.limit}{r.retryAfter && ` (retry in ${r.retryAfter}s)`}</td>
                    <td>{r.instance}</td>
                    <td><code>{r.requestId.slice(0, 8)}</code></td>
                    <td className="clip" title={r.body}>{r.body}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
