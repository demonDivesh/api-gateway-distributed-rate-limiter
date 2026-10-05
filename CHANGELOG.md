# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/), versioning: [SemVer](https://semver.org/).

## [1.0.0] - 2026-09-28

### Added
- API gateway (FastAPI): JWT access/refresh auth with rotation and Redis-backed revocation, role-aware routing, reverse proxy with streaming, retries for idempotent requests, request-size and path validation.
- Distributed rate limiter: atomic Redis Lua sliding-window and token-bucket algorithms, per-user / per-IP / per-role limits, strict limits on auth endpoints, standard `X-RateLimit-*` and `Retry-After` headers, configurable fail-open/fail-closed.
- Load balancing (round-robin, least-connections, random), active health checks, per-instance circuit breakers.
- Correlation IDs, structured JSON access logs, Prometheus `/metrics`, JSON summary endpoint, security headers, CORS, uniform error envelope.
- Service A (catalog, atomic stock reservation) and Service B (orders, service-to-service calls with compensation).
- React + TypeScript dashboard and request playground.
- Docker Compose stack (PostgreSQL, Redis, gateway, 2x service A, service B, frontend), Makefile, Locust load tests, end-to-end smoke test, full documentation.
