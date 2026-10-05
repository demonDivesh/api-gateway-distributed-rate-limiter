from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import fakeredis
import httpx
import pytest
import pytest_asyncio
from app.core.config import Settings
from app.infrastructure.database import create_engine
from app.main import create_app
from sqlalchemy.ext.asyncio import AsyncEngine


class FakeUpstream:
    """Programmable upstream behind an httpx.MockTransport."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.down: set[str] = set()  # hosts that refuse connections
        self.status_for: dict[str, int] = {}  # host -> forced status
        self.slow: set[str] = set()  # hosts that time out

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.url.path == "/health":
            if host in self.down:
                raise httpx.ConnectError("down", request=request)
            return httpx.Response(200, json={"status": "ok"})
        self.calls.append(request)
        if host in self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if host in self.slow:
            raise httpx.ReadTimeout("timeout", request=request)
        status = self.status_for.get(host, 200)
        body = {
            "host": host,
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query.decode(),
            "headers": dict(request.headers.items()),
            "body": request.content.decode() if request.content else "",
        }
        return httpx.Response(
            status,
            stream=httpx.ByteStream(json.dumps(body).encode()),
            headers={"x-instance-id": host, "content-type": "application/json"},
        )


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "environment": "test",
            "log_json": False,
            "log_level": "WARNING",
            "database_url": "sqlite+aiosqlite:///:memory:",
            "jwt_secret": "test-secret-test-secret-test-secret",
            "service_a_urls": "http://a1:8000,http://a2:8000",
            "service_b_urls": "http://b1:8000",
            "internal_secret": "test-internal",
            "admin_username": "admin",
            "admin_password": "admin-pass-123",
            "rate_limit_anonymous_per_minute": 1000,
            "rate_limit_user_per_minute": 1000,
            "rate_limit_admin_per_minute": 1000,
            "rate_limit_auth_per_minute": 1000,
            "cb_failure_threshold": 3,
            "cb_recovery_seconds": 60.0,
        }
        base.update(overrides)
        return Settings(**base)  # type: ignore[arg-type]

    return _make


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fakeredis.FakeAsyncRedis]:
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def app_factory(
    make_settings: Callable[..., Settings], redis_client, upstream: FakeUpstream
) -> AsyncIterator[Callable[..., tuple]]:
    """Builds started gateway apps. Yields callable(**settings) -> (app, client)."""
    stack: list = []
    engines: list[AsyncEngine] = []

    async def _build(**overrides: object):
        settings = make_settings(**overrides)
        engine = create_engine(settings.database_url)
        engines.append(engine)
        http = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler))
        app = create_app(
            settings,
            redis=redis_client,
            http_client=http,
            engine=engine,
            start_health_checker=False,
        )
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        stack.append((ctx, http))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 5555)),
            base_url="http://gateway.test",
        )
        stack.append((None, client))
        return app, client

    yield _build
    for ctx, resource in reversed(stack):
        if ctx is None:
            await resource.aclose()
        else:
            await ctx.__aexit__(None, None, None)
            await resource.aclose()
    for engine in engines:
        await engine.dispose()


@pytest_asyncio.fixture
async def gateway(app_factory):
    app, client = await app_factory()
    return app, client


async def login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def admin_token(gateway) -> str:
    _, client = gateway
    return (await login(client, "admin", "admin-pass-123"))["access_token"]


@pytest_asyncio.fixture
async def user_token(gateway) -> str:
    _, client = gateway
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "alice", "password": "alice-pass-123"}
    )
    assert resp.status_code == 201, resp.text
    return (await login(client, "alice", "alice-pass-123"))["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


__all__ = ["auth", "json", "login"]
