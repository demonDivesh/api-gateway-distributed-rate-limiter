import asyncio

import httpx
from app.core.config import Settings
from app.core.exceptions import PayloadTooLarge
from app.services.proxy_service import read_limited_body
from app.utils.net import client_ip

from tests.conftest import auth


async def test_trust_forwarded_for_uses_first_hop(app_factory, upstream):
    _, c = await app_factory(trust_forwarded_for=True)
    tok = (
        await c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    ).json()["access_token"]
    r = await c.get(
        "/api/service-a/x", headers={**auth(tok), "X-Forwarded-For": "198.51.100.7, 10.0.0.1"}
    )
    assert r.json()["headers"]["x-forwarded-for"] == "198.51.100.7"


def test_client_ip_ignores_forwarded_by_default():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.2.3.4")],
        "client": ("9.9.9.9", 1),
    }
    req = Request(scope)
    assert client_ip(req, False) == "9.9.9.9"
    assert client_ip(req, True) == "1.2.3.4"
    assert client_ip(Request({"type": "http", "headers": []}), False) == "unknown"


async def test_streamed_body_limit_without_content_length():
    from starlette.requests import Request

    chunks = [b"a" * 60, b"b" * 60]

    async def receive():
        if chunks:
            return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
        return {"type": "http.disconnect"}

    req = Request({"type": "http", "headers": [], "method": "POST"}, receive)
    try:
        await read_limited_body(req, 100)
    except PayloadTooLarge:
        return
    raise AssertionError("expected PayloadTooLarge")


async def test_health_checker_background_loop(app_factory, upstream):
    app, _ = await app_factory(health_check_interval_seconds=0.05)
    await app.state.health_checker.start()
    upstream.down.add("a1")
    await asyncio.sleep(0.3)
    await app.state.health_checker.stop()
    inst = app.state.load_balancer.pool("service-a").instances[0]
    assert inst.healthy is False


async def test_non_numeric_content_length_rejected(gateway):
    app, c = gateway
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as raw:
        r = await raw.get("/health", headers={"Content-Length": "abc"})
    assert r.status_code in (400, 422)


def test_settings_defaults_load():
    assert Settings().rate_limit_algorithm == "sliding_window"
