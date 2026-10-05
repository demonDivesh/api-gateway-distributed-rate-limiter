# Architecture

## Layers (gateway)

```
api/routes   HTTP surface (auth, health, metrics, catch-all proxy)
middleware   cross-cutting: security headers → request id → access log/metrics → validation → rate limit
services     business logic: auth, proxy, rate limiter, load balancer, circuit breaker, health checker
infrastructure  Redis / SQLAlchemy engine / httpx client factories
core         config, logging, security primitives, exceptions
```

`create_app(settings, redis=, http_client=, engine=)` is a factory with injectable infrastructure – production wires real clients in the lifespan; tests inject fakes. All state lives on `app.state`, created in the lifespan.

## Request pipeline

Outermost → innermost: CORS · SecurityHeaders · RequestID · AccessLog (+metrics, last-resort 500) · RequestValidation (method allow-list, path traversal, content-length) · RateLimit (opportunistic JWT decode → identity → Redis check) · route.

Authentication is *enforced* per route (proxy route config `auth_required`, `allowed_roles`), but *attempted* in the rate-limit middleware so limits can be per-user. An invalid token therefore yields `401` with the precise reason, and is rate limited by IP.

## Distributed rate limiting

Both algorithms are single Lua scripts (atomic in Redis, one round-trip):

- **Sliding window log** (sorted set, score = ms timestamp): exact, memory O(limit) per identity. `Retry-After` is derived from the oldest entry.
- **Token bucket** (hash: tokens, ts): allows bursts up to capacity, refills at `limit/window`. O(1) memory.

Time comes from Redis `TIME`, so gateway replicas with clock skew agree. Keys expire automatically. Any number of gateway replicas/workers share the same counters; concurrency tests assert exactly `limit` requests pass out of hundreds of simultaneous calls.
Failure mode is explicit: Redis errors → fail-open (default, availability) or fail-closed (503), counted in metrics.

## Proxying, load balancing, resilience

`ProxyService.forward`: validate → read body under size limit → build sanitized headers → loop up to `1+retries` attempts: select instance (healthy ∧ breaker permits ∧ not already tried) → reserve breaker slot → send (streamed) → classify. Responses stream back without buffering; connection accounting is released in a background task when the stream ends.

`UpstreamPool` strategies: round-robin, least-connections (ties rotate), random. `HealthChecker` polls `/health` on every instance (background task) and marks `healthy`; the breaker handles *in-flight* failures faster than polling can. Breaker: closed → (N failures) open → (recovery timeout) half-open → (M probe successes) closed, any probe failure re-opens.

## Data

PostgreSQL, database-per-service: `gateway` (users), `service_a` (items), `service_b` (orders). Service B never reads Service A's tables – it calls Service A's internal API (`/internal/items/{id}/reserve|release`) authenticated by a service token. Ordering: reserve stock (atomic `UPDATE … WHERE stock >= qty`) → persist order → on persistence failure, release stock (compensation). Cancelling releases stock.

## Deployment & path to Kubernetes

Twelve-factor: config via env, logs to stdout (JSON), stateless processes, health endpoints (`/health` liveness, `/health/ready` readiness), graceful lifespan shutdown, non-root images. Compose networks split `edge` and internal `backend`.

To move to Kubernetes: one Deployment per component; `/health` → livenessProbe, `/health/ready` → readinessProbe; Secrets for the four secrets; Redis and Postgres as managed services or StatefulSets; replace the static `SERVICE_*_URLS` list with a headless Service (or keep DNS-based instance discovery by resolving the headless name) or delegate balancing to the mesh/Service; scrape `/metrics` with a ServiceMonitor; put an Ingress in front and set `TRUST_FORWARDED_FOR=true` only for the ingress' address range. Nothing in the code depends on Compose.

## Known limitations (deliberate for v1)

- Breaker and health state are per gateway process (each replica learns independently); acceptable because failures are observed by all replicas quickly. A shared breaker would need Redis state.
- Schema created with `create_all`; no migrations framework yet.
- Access tokens are bearer JWTs (HS256, shared secret). Move to asymmetric keys (RS/EdDSA + JWKS) if other parties must verify tokens.
- No WebSocket proxying; request bodies are buffered up to 1 MiB (responses stream).
