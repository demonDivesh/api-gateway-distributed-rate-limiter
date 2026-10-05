import json
from collections import Counter

from tests.conftest import auth


async def test_proxy_requires_authentication(gateway):
    _, c = gateway
    r = await c.get("/api/service-a/items")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


async def test_unknown_service_404(gateway, user_token):
    _, c = gateway
    r = await c.get("/api/nope/x", headers=auth(user_token))
    assert r.status_code == 404 and r.json()["error"]["code"] == "route_not_found"


async def test_forwarding_strips_prefix_and_adds_identity_headers(gateway, user_token, upstream):
    _, c = gateway
    r = await c.post(
        "/api/service-a/items/7?x=1&y=two",
        content=b'{"a":1}',
        headers={**auth(user_token), "content-type": "application/json"},
    )
    assert r.status_code == 200
    seen = r.json()
    assert seen["path"] == "/items/7" and seen["query"] == "x=1&y=two"
    assert seen["method"] == "POST" and json.loads(seen["body"]) == {"a": 1}
    h = seen["headers"]
    assert h["x-user-name"] == "alice" and h["x-user-role"] == "user" and h["x-user-id"]
    assert h["x-gateway-secret"] == "test-internal"
    assert h["x-request-id"] == r.headers["x-request-id"]
    assert "authorization" not in h
    assert r.headers["x-gateway-upstream"] == "service-a"


async def test_client_cannot_spoof_identity_headers(gateway, user_token, upstream):
    _, c = gateway
    r = await c.get(
        "/api/service-a/x",
        headers={
            **auth(user_token),
            "X-User-Role": "admin",
            "X-Gateway-Secret": "guess",
            "X-Forwarded-For": "6.6.6.6",
            "Cookie": "s=1",
        },
    )
    h = r.json()["headers"]
    assert h["x-user-role"] == "user"
    assert h["x-gateway-secret"] == "test-internal"
    assert h["x-forwarded-for"] == "203.0.113.9"
    assert "cookie" not in h


async def test_round_robin_across_instances(gateway, user_token):
    _, c = gateway
    hosts = Counter()
    for _ in range(10):
        hosts[(await c.get("/api/service-a/x", headers=auth(user_token))).json()["host"]] += 1
    assert hosts == {"a1": 5, "a2": 5}


async def test_request_id_is_propagated_or_generated(gateway, user_token):
    _, c = gateway
    r = await c.get(
        "/api/service-b/x", headers={**auth(user_token), "X-Request-ID": "trace-12345678"}
    )
    assert r.headers["x-request-id"] == "trace-12345678"
    assert r.json()["headers"]["x-request-id"] == "trace-12345678"
    r = await c.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert (
        r.headers["x-request-id"] != "bad id with spaces" and len(r.headers["x-request-id"]) == 32
    )


async def test_retries_idempotent_request_on_failed_instance(gateway, user_token, upstream):
    _, c = gateway
    upstream.down.add("a1")
    for _ in range(6):
        r = await c.get("/api/service-a/x", headers=auth(user_token))
        assert r.status_code == 200 and r.json()["host"] == "a2"


async def test_post_is_not_retried(gateway, user_token, upstream):
    _, c = gateway
    upstream.down.add("a1")
    r = await c.post("/api/service-a/x", json={}, headers=auth(user_token))  # round-robin picks a1
    assert r.status_code == 503
    assert [q.url.host for q in upstream.calls] == ["a1"]  # a2 was never tried


async def test_all_instances_down_returns_503(gateway, user_token, upstream):
    _, c = gateway
    upstream.down.update({"a1", "a2"})
    r = await c.get("/api/service-a/x", headers=auth(user_token))
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"


async def test_timeout_maps_to_504(gateway, user_token, upstream):
    _, c = gateway
    upstream.slow.add("b1")
    r = await c.get("/api/service-b/x", headers=auth(user_token))
    assert r.status_code == 504 and r.json()["error"]["code"] == "upstream_timeout"


async def test_upstream_4xx_is_passed_through_and_not_a_breaker_failure(
    gateway, user_token, upstream
):
    app, c = gateway
    upstream.status_for["b1"] = 404
    for _ in range(10):
        assert (await c.get("/api/service-b/x", headers=auth(user_token))).status_code == 404
    inst = app.state.load_balancer.pool("service-b").instances[0]
    assert inst.breaker.snapshot()["state"] == "closed"


async def test_circuit_opens_then_fails_fast_without_hitting_upstream(
    gateway, user_token, upstream
):
    app, c = gateway
    upstream.status_for["b1"] = 500
    for _ in range(3):  # threshold = 3
        assert (
            await c.post("/api/service-b/x", json={}, headers=auth(user_token))
        ).status_code == 500
    before = len(upstream.calls)
    r = await c.post("/api/service-b/x", json={}, headers=auth(user_token))
    assert r.status_code == 503
    assert len(upstream.calls) == before
    assert (
        app.state.load_balancer.pool("service-b").instances[0].breaker.snapshot()["state"] == "open"
    )


async def test_circuit_recovers_via_half_open(gateway, user_token, upstream):
    app, c = gateway
    inst = app.state.load_balancer.pool("service-b").instances[0]
    upstream.status_for["b1"] = 500
    for _ in range(3):
        await c.post("/api/service-b/x", json={}, headers=auth(user_token))
    assert inst.breaker.snapshot()["state"] == "open"
    inst.breaker._opened_at -= 120  # recovery window (60s) elapsed
    upstream.status_for.pop("b1")
    for _ in range(2):  # half_open_max_calls = 2 successful probes close it
        assert (await c.get("/api/service-b/x", headers=auth(user_token))).status_code == 200
    assert inst.breaker.snapshot()["state"] == "closed"


async def test_unhealthy_instance_is_skipped(gateway, user_token):
    app, c = gateway
    app.state.load_balancer.pool("service-a").instances[0].healthy = False
    hosts = {
        (await c.get("/api/service-a/x", headers=auth(user_token))).json()["host"] for _ in range(6)
    }
    assert hosts == {"a2"}


async def test_oversized_body_rejected(app_factory, user_token=None):
    _, c = await app_factory(max_request_body_bytes=100)
    r = await c.post(
        "/api/v1/auth/login", content=b"x" * 500, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


async def test_path_traversal_rejected(gateway, user_token):
    _, c = gateway
    r = await c.get("/api/service-a/%2e%2e/admin", headers=auth(user_token))
    assert r.status_code == 400
    r = await c.get("/api/service-a/a/%2E%2E/b", headers=auth(user_token))
    assert r.status_code == 400


async def test_unsupported_method_rejected(gateway):
    _, c = gateway
    r = await c.request("TRACE", "/health")
    assert r.status_code == 405


async def test_role_restricted_route(gateway, user_token, admin_token):
    app, c = gateway
    app.state.routes["/api/service-b"].allowed_roles = ["admin"]
    assert (await c.get("/api/service-b/x", headers=auth(user_token))).status_code == 403
    assert (await c.get("/api/service-b/x", headers=auth(admin_token))).status_code == 200


async def test_invalid_token_on_proxy_route_reports_reason(gateway):
    _, c = gateway
    r = await c.get("/api/service-a/x", headers=auth("not.a.jwt"))
    assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid token"
