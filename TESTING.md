# Testing

| Suite | Command | Count | Notes |
|---|---|---|---|
| Gateway unit + integration | `make test-gateway` | 102 | ~94% line coverage; SQLite + fakeredis (real Lua) + `httpx.MockTransport` upstreams |
| Service A / B | `make test-services` | 10 / 9 | SQLite file DB (real concurrency), mocked catalog transport |
| Frontend | `make test-frontend` | 5 + typecheck + build | vitest + Testing Library |
| Limiter load | `make load` | 2 | 4,000 concurrent checks must never exceed limits |
| End-to-end | `make up && make e2e` | 32 checks | Real PostgreSQL + Redis + all services |
| Locust | see `load_test/README.md` | – | throughput / failover behaviour |

What is covered: both limiter algorithms (boundaries, refill, isolation, atomicity under concurrency, multi-replica sharing, server-clock use), fail-open/closed, breaker state machine and its integration (open → fail-fast → half-open → closed), retries/failover, timeouts→504, header spoofing, path traversal, body limits, JWT edge cases (expired, tampered, alg=none, wrong type, missing claims), refresh rotation and revocation, RBAC, CORS, production hardening, health/readiness, metrics.

Not covered by automated tests in this repo: Docker image builds and `docker compose up` (require a Docker daemon) – validated by `make e2e` on a running stack.
