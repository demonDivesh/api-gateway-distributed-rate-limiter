from tests.conftest import auth


async def test_liveness_and_security_headers(gateway):
    _, c = gateway
    r = await c.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]


async def test_readiness_ok(gateway):
    _, c = gateway
    r = await c.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["redis"] == "ok" and body["checks"]["database"] == "ok"


async def test_readiness_reports_redis_outage(gateway):
    app, c = gateway

    class Broken:
        async def ping(self):
            raise ConnectionError("down")

    app.state.redis = Broken()
    r = await c.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["redis"] == "unavailable"


async def test_health_checker_marks_instances(gateway, upstream):
    app, _ = gateway
    upstream.down.add("a2")
    await app.state.health_checker.check_all()
    a = {i.url: i for i in app.state.load_balancer.pool("service-a").instances}
    assert a["http://a1:8000"].healthy and not a["http://a2:8000"].healthy
    assert a["http://a2:8000"].last_error == "ConnectError"
    upstream.down.clear()
    await app.state.health_checker.check_all()
    assert a["http://a2:8000"].healthy


async def test_upstreams_endpoint(gateway):
    _, c = gateway
    r = await c.get("/health/upstreams")
    names = {p["name"] for p in r.json()}
    assert names == {"service-a", "service-b"}


async def test_prometheus_metrics(gateway, user_token):
    _, c = gateway
    await c.get("/api/service-a/x", headers=auth(user_token))
    r = await c.get("/metrics")
    assert r.status_code == 200 and "text/plain" in r.headers["content-type"]
    assert "gateway_http_requests_total" in r.text
    assert 'gateway_upstream_requests_total{outcome="success",service="service-a"}' in r.text
    assert "gateway_circuit_breaker_state" in r.text


async def test_metrics_token_protection(app_factory):
    _, c = await app_factory(metrics_token="s3cr3t-metrics-token")
    assert (await c.get("/metrics")).status_code == 401
    assert (await c.get("/metrics", headers=auth("wrong"))).status_code == 401
    assert (await c.get("/metrics", headers=auth("s3cr3t-metrics-token"))).status_code == 200


async def test_summary_requires_auth_and_reports(gateway, user_token):
    _, c = gateway
    assert (await c.get("/api/v1/metrics/summary")).status_code == 401
    r = await c.get("/api/v1/metrics/summary", headers=auth(user_token))
    body = r.json()
    assert r.status_code == 200
    assert body["total_requests"] >= 1 and len(body["upstreams"]) == 2
    assert body["rate_limit_config"]["algorithm"] == "sliding_window"


async def test_openapi_docs_available_outside_production(gateway):
    _, c = gateway
    r = await c.get("/openapi.json")
    assert r.status_code == 200 and "/api/v1/auth/login" in r.json()["paths"]


async def test_docs_disabled_in_production(app_factory):
    _, c = await app_factory(
        environment="production",
        jwt_secret="p" * 40,
        admin_password="strong-admin-pw-1",
        internal_secret="q" * 40,
    )
    assert (await c.get("/openapi.json")).status_code == 404
    assert "strict-transport-security" in (await c.get("/health")).headers


async def test_cors_preflight_and_exposed_headers(gateway):
    _, c = gateway
    r = await c.options(
        "/api/service-a/x",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = await c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


async def test_unhandled_error_returns_json_500_with_request_id(gateway, user_token, monkeypatch):
    app, c = gateway

    async def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(app.state.proxy, "forward", boom)
    r = await c.get("/api/service-a/x", headers=auth(user_token))
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "internal_error" and err["message"] == "Internal server error"
    assert err["request_id"] == r.headers["x-request-id"]
    assert "kaboom" not in r.text
