# API Gateway & Distributed Rate Limiter

A production-style API gateway in front of two backend services, with JWT authentication, **Redis-backed distributed rate limiting**, load balancing, health checks, circuit breaking, structured logging, Prometheus metrics and a React dashboard.

```
Client / React dashboard
        │
        ▼
   API Gateway  ───────►  Redis  (rate limits, token revocation)
        │        ───────►  PostgreSQL (users)
   ┌────┴──────────┐
   ▼               ▼
Service A (×2)   Service B  ──► Service A (service-to-service, reserve stock)
   └───────┬───────┘
           ▼
      PostgreSQL (one database per service)
```

| Capability | Where |
|---|---|
| JWT auth (access + rotating refresh tokens, revocation, roles) | `gateway/app/services/auth_service.py`, `core/security.py` |
| Distributed rate limiting (sliding window / token bucket, Lua, atomic) | `services/rate_limiter.py`, `middleware/rate_limit.py` |
| Reverse proxy, retries, streaming, header hygiene | `services/proxy_service.py`, `api/routes/gateway.py` |
| Load balancing (round-robin / least-connections / random) | `services/load_balancer.py` |
| Health checks (active) + readiness endpoint | `services/health_checker.py`, `api/routes/health.py` |
| Circuit breaker (per upstream instance) | `services/circuit_breaker.py` |
| Request IDs, JSON logs, metrics, security headers, validation | `middleware/`, `core/logging.py`, `utils/metrics.py` |
| Dashboard + request playground | `frontend/` |

## Quick start (Docker)

Requires Docker with Compose v2.

```bash
cp .env.example .env
# edit .env: set JWT_SECRET, INTERNAL_SECRET, SERVICE_TOKEN, POSTGRES_PASSWORD, ADMIN_PASSWORD
docker compose up --build
```

- Dashboard: http://localhost:3000 (sign in as `admin` with your `ADMIN_PASSWORD`, or register)
- Gateway API + Swagger UI: http://localhost:8000/docs
- Prometheus metrics: http://localhost:8000/metrics

Try it:

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/api/service-a/whoami -H "Authorization: Bearer $TOKEN"     # note X-Instance-Id alternating
curl -s -X POST localhost:8000/api/service-a/items -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"name":"Widget","price_cents":1500,"stock":10}'
curl -s -X POST localhost:8000/api/service-b/orders -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"item_id":1,"quantity":2}'
make e2e        # full smoke test against the running stack
```

Docker note: images use `python:3.14-slim`. To pin an exact patch (e.g. 3.14.6):
`docker compose build --build-arg PYTHON_IMAGE=python:3.14.6-slim` (or set the `ARG` default in the Dockerfiles).

## Local development

```bash
make install                 # Python 3.14 venv + npm ci
make test                    # gateway (102 tests), services, frontend
make lint typecheck
cd frontend && npm run dev   # dashboard on :5173 (proxies to a gateway on :8000)
```

Running the processes without Docker requires PostgreSQL and Redis; see the env vars below and `scripts/e2e_smoke.py`.
Tests need neither: they use SQLite, `fakeredis` (with real Lua execution) and mocked HTTP transports.

## Configuration (gateway)

All settings are environment variables (see `gateway/app/core/config.py`, `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `ENVIRONMENT` | development | `production` refuses default secrets, hides `/docs`, enables HSTS |
| `JWT_SECRET` | – | ≥16 chars (use 32+). |
| `ACCESS_TOKEN_TTL_SECONDS` / `REFRESH_TOKEN_TTL_SECONDS` | 900 / 604800 | |
| `RATE_LIMIT_ALGORITHM` | sliding_window | or `token_bucket` |
| `RATE_LIMIT_{ANONYMOUS,USER,ADMIN,AUTH}_PER_MINUTE` | 30 / 120 / 600 / 10 | limit by identity; AUTH is per IP for login/register/refresh |
| `RATE_LIMIT_FAIL_OPEN` | true | serve traffic if Redis is down (else 503) |
| `AUTH_REVOCATION_FAIL_OPEN` | false | accept tokens if Redis (revocation list) is down |
| `TRUST_FORWARDED_FOR` | false | honour `X-Forwarded-For` (only behind a trusted proxy!) |
| `LOAD_BALANCER_STRATEGY` | round_robin | `least_connections`, `random` |
| `SERVICE_A_URLS`, `SERVICE_B_URLS` | compose hosts | comma-separated upstream instances |
| `CB_FAILURE_THRESHOLD` / `CB_RECOVERY_SECONDS` / `CB_HALF_OPEN_MAX_CALLS` | 5 / 15 / 2 | circuit breaker |
| `HEALTH_CHECK_INTERVAL_SECONDS` | 5 | |
| `MAX_REQUEST_BODY_BYTES` | 1048576 | |
| `METRICS_TOKEN` | empty | if set, `/metrics` requires this bearer token |

## Behaviour worth knowing

- **Rate limit identity**: authenticated user id, else client IP. Exempt: `/health*`, `/metrics`, docs. Responses carry `X-RateLimit-Limit/Remaining/Reset`; rejections are `429` with `Retry-After`.
- **Failover**: idempotent methods (GET/HEAD/PUT/DELETE/OPTIONS) are retried on another instance after connection errors, timeouts or 502/503/504. POST/PATCH are never retried automatically.
- **Circuit breaker** opens after N consecutive 5xx/connection failures, fails fast, then half-opens to probe. 4xx never count.
- **Trust boundary**: the gateway strips client-supplied `X-User-*`, `X-Gateway-*`, `X-Forwarded-*`, `Authorization`, `Cookie`, then sets identity headers + a shared secret; backend services reject requests lacking the secret.
- **Schema management**: tables are created on startup (guarded by a Postgres advisory lock for concurrent replicas). For evolving schemas introduce Alembic before the first production migration.
- **Circuit-breaker state is per gateway process** (health state too); rate limits and token revocation are shared via Redis. See `ARCHITECTURE.md` for scaling and Kubernetes notes.

## Repository layout

`gateway/` gateway app + tests · `services/service_a|b/` backends + tests · `frontend/` dashboard · `load_test/` Locust · `scripts/e2e_smoke.py` end-to-end check · `infra/` DB init · docs: `ARCHITECTURE.md`, `API.md`, `SECURITY.md`, `TESTING.md`, `CONTRIBUTING.md`, `CHANGELOG.md`.
