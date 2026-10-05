#!/usr/bin/env python3
"""End-to-end smoke test against a *running* stack (docker compose or local processes).

Usage:
    python scripts/e2e_smoke.py [--base-url http://localhost:8000] [--admin-password ...]

Exercises: auth, proxying, load balancing, service-to-service calls (orders reserve stock in
the catalog), authorization, rate limiting against real Redis, and metrics. Exits non-zero
on the first failed check.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections import Counter

import httpx

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(
        f"  [{'PASS' if condition else 'FAIL'}] {name}"
        + (f"  ({detail})" if detail and not condition else "")
    )
    if not condition:
        failures += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--admin-user", default="admin")
    ap.add_argument("--admin-password", default="admin-change-me")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base_url, timeout=10)

    print("health")
    check("liveness", c.get("/health").status_code == 200)
    ready = c.get("/health/ready")
    check("readiness (redis + postgres + upstreams)", ready.status_code == 200, ready.text)

    print("auth")
    name = f"smoke-{uuid.uuid4().hex[:8]}"
    check(
        "register",
        c.post(
            "/api/v1/auth/register",
            json={"username": name, "password": "smoke-pass-123"},
        ).status_code
        == 201,
    )
    r = c.post("/api/v1/auth/login", json={"username": name, "password": "smoke-pass-123"})
    check("login", r.status_code == 200, r.text)
    tokens = r.json()
    user = {"Authorization": f"Bearer {tokens['access_token']}"}
    admin_tokens = c.post(
        "/api/v1/auth/login",
        json={"username": args.admin_user, "password": args.admin_password},
    )
    check("admin login", admin_tokens.status_code == 200, admin_tokens.text)
    admin = {"Authorization": f"Bearer {admin_tokens.json()['access_token']}"}
    check(
        "anonymous proxy call rejected",
        c.get("/api/service-a/items").status_code == 401,
    )
    check("me", c.get("/api/v1/auth/me", headers=user).json()["username"] == name)

    print("proxy + load balancing")
    seen = Counter()
    for _ in range(10):
        r = c.get("/api/service-a/whoami", headers=user)
        seen[r.headers.get("x-instance-id")] += 1
    check(
        "service-a whoami served",
        sum(seen.values()) == 10 and None not in seen,
        str(seen),
    )
    check("traffic spread over >1 instance", len(seen) > 1, str(seen))
    check(
        "identity propagated",
        r.json()["user_name"] == name and r.json()["role"] == "user",
    )
    check("request id echoed", bool(r.headers.get("x-request-id")))

    print("service A catalog")
    r = c.post(
        "/api/service-a/items",
        json={"name": "Smoke widget", "price_cents": 1500, "stock": 10},
        headers=user,
    )
    check("create item", r.status_code == 201, r.text)
    item = r.json()
    check(
        "get item",
        c.get(f"/api/service-a/items/{item['id']}", headers=admin).status_code == 200,
    )
    r = c.post(
        "/api/service-a/items",
        json={"name": "Owned", "price_cents": 100, "stock": 1},
        headers=admin,
    )
    check(
        "user cannot delete admin's item",
        c.delete(f"/api/service-a/items/{r.json()['id']}", headers=user).status_code == 403,
    )
    check(
        "internal endpoints not reachable by users",
        c.post(
            f"/api/service-a/internal/items/{item['id']}/reserve",
            json={"quantity": 1},
            headers=user,
        ).status_code
        == 403,
    )
    check(
        "validation error envelope",
        c.post("/api/service-a/items", json={"name": ""}, headers=user).status_code == 422,
    )

    print("service B orders (service-to-service)")
    r = c.post(
        "/api/service-b/orders",
        json={"item_id": item["id"], "quantity": 4},
        headers=user,
    )
    check("create order", r.status_code == 201 and r.json()["total_cents"] == 6000, r.text)
    order = r.json()
    stock = c.get(f"/api/service-a/items/{item['id']}", headers=user).json()["stock"]
    check("stock reserved in catalog", stock == 6, f"stock={stock}")
    check(
        "oversell rejected",
        c.post(
            "/api/service-b/orders",
            json={"item_id": item["id"], "quantity": 7},
            headers=user,
        ).status_code
        == 409,
    )
    check(
        "unknown item",
        c.post(
            "/api/service-b/orders",
            json={"item_id": 999999, "quantity": 1},
            headers=user,
        ).status_code
        == 404,
    )
    check(
        "cancel releases stock",
        c.post(f"/api/service-b/orders/{order['id']}/cancel", headers=user).status_code == 200
        and c.get(f"/api/service-a/items/{item['id']}", headers=user).json()["stock"] == 10,
    )
    check(
        "orders are private",
        c.get(
            f"/api/service-b/orders/{order['id']}",
            headers={"Authorization": admin["Authorization"]},
        ).status_code
        == 200,
    )

    print("token lifecycle")
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("refresh", r.status_code == 200)
    check(
        "refresh token is single-use",
        c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code
        == 401,
    )
    new = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("logout", c.post("/api/v1/auth/logout", json={}, headers=new).status_code == 204)
    check(
        "revoked token rejected",
        c.get("/api/v1/auth/me", headers=new).status_code == 401,
    )

    print("rate limiting (real Redis)")
    fresh = f"{name}-rl"  # a fresh identity so earlier requests don't count against this window
    c.post("/api/v1/auth/register", json={"username": fresh, "password": "smoke-pass-123"})
    r = c.post("/api/v1/auth/login", json={"username": fresh, "password": "smoke-pass-123"})
    limited_user = {"Authorization": f"Bearer {r.json()['access_token']}"}
    first = c.get("/api/service-a/whoami", headers=limited_user)
    limit = int(first.headers["x-ratelimit-limit"])
    codes = [first.status_code] + [
        c.get("/api/service-a/whoami", headers=limited_user).status_code for _ in range(limit + 5)
    ]
    ok, blocked = codes.count(200), codes.count(429)
    check(
        f"exactly {limit} requests allowed per window",
        ok == limit and blocked >= 5,
        f"200s={ok} 429s={blocked}",
    )
    r = c.get("/api/service-a/whoami", headers=limited_user)
    check(
        "429 carries Retry-After + RateLimit headers",
        r.status_code == 429
        and int(r.headers["retry-after"]) >= 1
        and r.headers["x-ratelimit-remaining"] == "0",
        str(dict(r.headers)),
    )
    check(
        "other users unaffected",
        c.get("/api/service-a/whoami", headers=admin).status_code == 200,
    )

    print("metrics")
    text = c.get("/metrics").text
    check(
        "prometheus exposition",
        "gateway_http_requests_total" in text and "gateway_circuit_breaker_state" in text,
    )
    time.sleep(0.1)
    s = c.get("/api/v1/metrics/summary", headers=admin).json()
    check(
        "summary reports limited requests",
        s["rate_limit"]["limited"] >= 5,
        str(s["rate_limit"]),
    )

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
