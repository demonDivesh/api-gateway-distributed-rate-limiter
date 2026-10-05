# Load testing

Two complementary tools:

| Tool | Purpose |
|------|---------|
| `locustfile.py` | Realistic mixed traffic (register/login/CRUD/orders) against a running stack. |
| `gateway/tests/load/test_limiter_load.py` | In-process, deterministic stress of the rate limiter's atomicity (pytest, marker `load`). |

## Locust

```bash
pip install -r gateway/requirements-dev.txt locust
docker compose up -d --build
locust -f load_test/locustfile.py --host http://localhost:8000          # web UI on :8089
locust -f load_test/locustfile.py --host http://localhost:8000 -u 100 -r 20 -t 2m --headless --csv out/run
```

Defaults limit each user to 120 req/min, so a large run mostly measures the limiter (lots of 429s,
reported as `... [429 limited]`). To measure raw proxy throughput, start the stack with
`RATE_LIMIT_USER_PER_MINUTE=100000 RATE_LIMIT_AUTH_PER_MINUTE=100000` (registration is limited per IP,
so many simulated users from one machine need the higher auth limit).

What to watch: p95/p99 latency, failure rate (should be ~0), and the dashboard's per-instance request
counts (load should be spread evenly). Kill a `service-a-*` container mid-run to observe failover:
failures should stay ~0 because idempotent requests are retried on another instance and the circuit opens.

## In-process limiter load test

```bash
cd gateway && pytest -m load tests/load
```
