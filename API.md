# API reference

Interactive docs: `GET /docs` (disabled when `ENVIRONMENT=production`). All errors share one envelope:

```json
{"error": {"code": "rate_limited", "message": "Rate limit exceeded. Try again later.", "request_id": "…", "details": []}}
```

Every response has `X-Request-ID` (client-supplied `[A-Za-z0-9._-]{8,64}` is honoured, else generated).

## Gateway

| Method & path | Auth | Description |
|---|---|---|
| `POST /api/v1/auth/register` `{username,password}` | – | 201 user. Username 3–32 `[A-Za-z0-9_.-]`, password 8–128. 409 if taken, 403 if disabled. |
| `POST /api/v1/auth/login` `{username,password}` | – | `{access_token, refresh_token, token_type, expires_in}` |
| `POST /api/v1/auth/refresh` `{refresh_token}` | – | New pair; the old refresh token is revoked (single use). |
| `POST /api/v1/auth/logout` `{refresh_token?}` | Bearer | 204; revokes the access (and refresh) token. |
| `GET /api/v1/auth/me` | Bearer | Current user. |
| `GET /api/v1/metrics/summary` | Bearer | Totals, latency percentiles, rate-limit counters, upstream state. |
| `GET /health` · `/health/ready` · `/health/upstreams` | – | Liveness · readiness (Redis, DB) · per-instance state. |
| `GET /metrics` | optional token | Prometheus exposition. |
| `ANY /api/{service}/{path}` | Bearer | Reverse proxy to `service-a` / `service-b`. |

Rate-limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (epoch seconds); `429` adds `Retry-After` (seconds).
Status codes added by the gateway: 400 (illegal path / Content-Length), 401, 403, 404 (`route_not_found`), 405, 413, 429, 502-class mapped to 503 `upstream_unavailable` / 504 `upstream_timeout`.

## Service A – catalog (`/api/service-a/…`)

| Endpoint | Notes |
|---|---|
| `GET /items?q=&limit=&offset=` | search by name, limit ≤ 100 |
| `POST /items` `{name, description?, price_cents, stock?}` | owner = caller |
| `GET/PATCH/DELETE /items/{id}` | PATCH/DELETE: owner or admin, else 403 |
| `GET /whoami` | shows serving instance + identity headers received |

`/internal/*` (stock reserve/release) requires the service token and is for Service B only; users calling it through the gateway get 403.

## Service B – orders (`/api/service-b/…`)

| Endpoint | Notes |
|---|---|
| `POST /orders` `{item_id, quantity}` | 201; 404 unknown item; 409 insufficient stock; 503 catalog down |
| `GET /orders?limit=&offset=` | own orders (admin: all) |
| `GET /orders/{id}` | 404 if not yours |
| `POST /orders/{id}/cancel` | releases stock; 409 if already cancelled |
