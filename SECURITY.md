# Security

## Reporting
Email the maintainers privately; do not open public issues for vulnerabilities.

## Controls implemented
- **Authentication**: HS256 JWTs with required `exp/iat/jti/sub`, explicit algorithm allow-list (no `alg=none`), typed access vs refresh tokens, refresh rotation, Redis revocation list (fails closed by default), constant-time password check with dummy-hash for unknown users (no username enumeration), scrypt (N=2^14) password hashing.
- **Brute-force protection**: strict per-IP limit on login/register/refresh.
- **Trust boundary**: gateway strips inbound `Authorization`, `Cookie`, `X-User-*`, `X-Gateway-*`, `X-Forwarded-*`; backends accept only requests bearing the shared gateway secret (constant-time compare). Backend services are not published to the host and sit on an `internal` Docker network. Internal endpoints additionally need a service token.
- **Input validation**: Pydantic schemas everywhere; method allow-list; encoded/plain path traversal and control characters rejected; body limited (declared and streamed); query length limit.
- **Headers**: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, restrictive CSP on API responses, HSTS in production, `Cache-Control: no-store` on auth, `Server` header removed. Strict CORS allow-list, no credentials.
- **Errors**: uniform envelope; internals never leak (500s are generic, logged with request ID).
- **Operations**: non-root containers, secrets from env only, production mode refuses default secrets, docs disabled in production, optional bearer token on `/metrics`.

## Operator checklist
1. Generate all four secrets (≥32 random chars); never reuse them.
2. Terminate TLS in front of the gateway (Ingress/LB). Set `ENVIRONMENT=production`.
3. Set `TRUST_FORWARDED_FOR=true` only when the immediate peer is your trusted proxy – otherwise clients can spoof their IP and evade IP limits.
4. Consider `ALLOW_REGISTRATION=false` for closed systems; set `METRICS_TOKEN` or keep `/metrics` off the public network.
5. Do not expose Redis/Postgres. Use TLS and auth for managed instances.
6. Rotate `JWT_SECRET` by scheduling a maintenance window (invalidates sessions) or move to asymmetric keys.

## Known limits
Rate limiting keys on IP for anonymous traffic (NAT/shared IPs share a quota). Bearer tokens in `sessionStorage` are exposed to XSS – the dashboard ships a strict CSP and renders no untrusted HTML. Unbounded account creation is limited only by the per-IP registration limit.
