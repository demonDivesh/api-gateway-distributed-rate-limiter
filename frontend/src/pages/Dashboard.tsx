import { useEffect, useState } from 'react'
import { errorMessage, fetchSummary, type Summary } from '../api'

const POLL_MS = 3000

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${m}m` : m ? `${m}m ${seconds % 60}s` : `${seconds}s`
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'good' | 'bad' }) {
  return (
    <div className="card stat">
      <div className="muted">{label}</div>
      <div className={`stat-value ${tone ?? ''}`}>{value}</div>
    </div>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const data = await fetchSummary()
        if (active) {
          setSummary(data)
          setError(null)
        }
      } catch (err) {
        if (active) setError(errorMessage(err))
      }
    }
    void load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])

  if (!summary) return <p className="muted">{error ?? 'Loading metrics…'}</p>

  const total = summary.total_requests || 1
  const { allowed, limited } = summary.rate_limit
  return (
    <>
      <h1>Overview</h1>
      {error && <div className="alert">Refresh failed: {error}</div>}
      <section className="grid">
        <Stat label="Total requests" value={summary.total_requests.toLocaleString()} />
        <Stat label="p95 latency" value={`${summary.latency_ms.p95} ms`} />
        <Stat label="Rate limited" value={limited.toLocaleString()} tone={limited ? 'bad' : 'good'} />
        <Stat label="Uptime" value={formatUptime(summary.uptime_seconds)} />
      </section>

      <section className="card">
        <h2>Responses by class</h2>
        {Object.keys(summary.status_classes).length === 0 && <p className="muted">No traffic yet.</p>}
        {Object.entries(summary.status_classes).sort().map(([cls, count]) => (
          <div className="bar-row" key={cls}>
            <span className="bar-label">{cls}</span>
            <div className="bar"><div className={`bar-fill c${cls[0]}`} style={{ width: `${(count / total) * 100}%` }} /></div>
            <span className="bar-count">{count}</span>
          </div>
        ))}
        <p className="muted small">
          Rate limiter ({String(summary.rate_limit_config.algorithm)}): {allowed} allowed / {limited} rejected
          {summary.rate_limit.errors ? ` / ${summary.rate_limit.errors} backend errors` : ''}. Latency p50 {summary.latency_ms.p50} ms,
          p99 {summary.latency_ms.p99} ms over {summary.latency_ms.samples} samples.
        </p>
      </section>

      {summary.upstreams.map((pool) => (
        <section className="card" key={pool.name}>
          <h2>{pool.name} <span className="badge">{pool.strategy}</span></h2>
          <table>
            <thead>
              <tr><th>Instance</th><th>Health</th><th>Circuit</th><th>Active</th><th>Requests</th><th>Check latency</th></tr>
            </thead>
            <tbody>
              {pool.instances.map((i) => (
                <tr key={i.url}>
                  <td><code>{i.url}</code></td>
                  <td><span className={`pill ${i.healthy ? 'ok' : 'bad'}`}>{i.healthy ? 'healthy' : i.last_error ?? 'down'}</span></td>
                  <td><span className={`pill cb-${i.circuit_breaker.state}`}>{i.circuit_breaker.state.replace('_', '-')}</span></td>
                  <td>{i.active_connections}</td>
                  <td>{i.total_requests}</td>
                  <td>{i.last_latency_ms === null ? '—' : `${i.last_latency_ms} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  )
}
