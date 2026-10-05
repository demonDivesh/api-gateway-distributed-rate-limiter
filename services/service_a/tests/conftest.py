import httpx
import pytest_asyncio
from app.config import Settings
from app.database import create_engine
from app.main import create_app

GW = {
    "X-Gateway-Secret": "test-secret",
    "X-User-Id": "u-1",
    "X-User-Name": "alice",
    "X-User-Role": "user",
}
ADMIN = {**GW, "X-User-Id": "u-admin", "X-User-Name": "root", "X-User-Role": "admin"}
OTHER = {**GW, "X-User-Id": "u-2", "X-User-Name": "bob"}
SERVICE = {"X-Service-Token": "svc-token"}


@pytest_asyncio.fixture
async def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/a.db",
        internal_secret="test-secret",
        service_token="svc-token",
        instance_id="svc-a-test",
        log_level="WARNING",
    )
    engine = create_engine(settings.database_url)
    app = create_app(settings, engine)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://a"
        ) as c:
            yield c
    await engine.dispose()
