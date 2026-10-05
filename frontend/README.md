# Gateway dashboard

React 19 + TypeScript + Vite + React Router + Axios.

- **Dashboard** – live (3 s polling) request totals, latency percentiles, response classes, rate-limiter decisions, and per-instance health / circuit-breaker state / connections for every upstream pool (`GET /api/v1/metrics/summary`).
- **Playground** – send authenticated requests through the gateway, repeat them N times in parallel to trigger rate limiting, and see `X-RateLimit-*`, `Retry-After`, serving instance and request ID per response.
- Sign in / register; access tokens auto-refresh once on 401 (refresh tokens rotate). Tokens live in `sessionStorage`.

```bash
npm install
npm run dev            # http://localhost:5173, proxies /api and /health to VITE_GATEWAY_URL (default http://localhost:8000)
npm run build          # typecheck + production build
npm test               # vitest
```

In Docker the app is served by nginx, which proxies `/api` to the gateway so the browser only ever talks to one origin.
