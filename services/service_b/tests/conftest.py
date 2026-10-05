import httpx
import pytest
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
OTHER = {**GW, "X-User-Id": "u-2", "X-User-Name": "bob"}
ADMIN = {**GW, "X-User-Id": "u-admin", "X-User-Role": "admin"}


class FakeCatalog:
    """Stands in for Service A behind an httpx.MockTransport."""

    def __init__(self) -> None:
        self.items = {1: {"stock": 5, "price_cents": 250}}
        self.calls: list[tuple[str, str]] = []
        self.fail_with: int | None = None
        self.raise_connect = False
        self.attempts = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        self.calls.append((request.method, request.url.path))
        if self.raise_connect:
            raise httpx.ConnectError("refused", request=request)
        if self.fail_with:
            return httpx.Response(self.fail_with, json={"detail": "boom"})
        if request.headers.get("x-service-token") != "svc-token":
            return httpx.Response(403, json={"detail": "Internal endpoint"})
        parts = request.url.path.strip("/").split("/")  # internal/items/{id}[/action]
        item_id = int(parts[2])
        item = self.items.get(item_id)
        if item is None:
            return httpx.Response(404, json={"detail": "Item not found"})
        if len(parts) == 3:
            return httpx.Response(200, json={"id": item_id, **item})
        qty = int(__import__("json").loads(request.content)["quantity"])
        if parts[3] == "reserve":
            if item["stock"] < qty:
                return httpx.Response(409, json={"detail": "Insufficient stock"})
            item["stock"] -= qty
        else:
            item["stock"] += qty
        return httpx.Response(200, json={"id": item_id, **item})


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog()


@pytest_asyncio.fixture
async def client(tmp_path, catalog):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/b.db",
        internal_secret="test-secret",
        service_token="svc-token",
        instance_id="svc-b-test",
        catalog_url="http://catalog",
        catalog_retries=2,
        log_level="CRITICAL",
    )
    engine = create_engine(settings.database_url)
    http = httpx.AsyncClient(transport=httpx.MockTransport(catalog.handler))
    app = create_app(settings, engine, http)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://b"
        ) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
    await http.aclose()
    await engine.dispose()
