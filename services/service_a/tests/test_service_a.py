import asyncio

from tests.conftest import ADMIN, GW, OTHER, SERVICE

ITEM = {"name": "Widget", "description": "A widget", "price_cents": 1999, "stock": 10}


async def make(client, headers=GW, **over):
    r = await client.post("/items", json={**ITEM, **over}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_health_is_public_and_reports_instance(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["instance"] == "svc-a-test"
    assert r.headers["x-instance-id"] == "svc-a-test"


async def test_rejects_requests_that_bypass_gateway(client):
    assert (await client.get("/items")).status_code == 401
    assert (
        await client.get("/items", headers={**GW, "X-Gateway-Secret": "wrong"})
    ).status_code == 401
    no_user = {"X-Gateway-Secret": "test-secret"}
    assert (await client.get("/items", headers=no_user)).status_code == 401


async def test_whoami_echoes_identity(client):
    r = await client.get("/whoami", headers={**GW, "X-Request-ID": "rid-1"})
    assert r.json() == {
        "service": "service-a",
        "instance": "svc-a-test",
        "user_id": "u-1",
        "user_name": "alice",
        "role": "user",
        "request_id": "rid-1",
    }


async def test_crud_lifecycle(client):
    item = await make(client)
    assert item["owner_id"] == "u-1" and item["stock"] == 10
    got = await client.get(f"/items/{item['id']}", headers=OTHER)
    assert got.status_code == 200 and got.json()["name"] == "Widget"
    upd = await client.patch(f"/items/{item['id']}", json={"price_cents": 500}, headers=GW)
    assert upd.status_code == 200 and upd.json()["price_cents"] == 500
    assert (await client.delete(f"/items/{item['id']}", headers=GW)).status_code == 204
    assert (await client.get(f"/items/{item['id']}", headers=GW)).status_code == 404


async def test_ownership_enforced_and_admin_override(client):
    item = await make(client)
    assert (
        await client.patch(f"/items/{item['id']}", json={"name": "x"}, headers=OTHER)
    ).status_code == 403
    assert (await client.delete(f"/items/{item['id']}", headers=OTHER)).status_code == 403
    assert (
        await client.patch(f"/items/{item['id']}", json={"name": "Renamed"}, headers=ADMIN)
    ).status_code == 200
    assert (await client.delete(f"/items/{item['id']}", headers=ADMIN)).status_code == 204


async def test_validation(client):
    for bad in (
        {"name": "", "price_cents": 1},
        {"name": "x", "price_cents": -1},
        {"name": "x", "price_cents": 1, "stock": -5},
        {"price_cents": 1},
    ):
        assert (await client.post("/items", json=bad, headers=GW)).status_code == 422
    item = await make(client)
    assert (
        await client.patch(f"/items/{item['id']}", json={"name": None}, headers=GW)
    ).status_code == 422


async def test_list_search_and_pagination(client):
    for n in ("Apple", "Banana", "apple pie", "Cherry"):
        await make(client, name=n)
    r = await client.get("/items?q=APPLE", headers=GW)
    assert r.json()["total"] == 2
    page = await client.get("/items?limit=2&offset=1", headers=GW)
    body = page.json()
    assert body["total"] == 4 and len(body["items"]) == 2 and body["offset"] == 1
    assert (await client.get("/items?limit=1000", headers=GW)).status_code == 422


async def test_internal_endpoints_need_service_token(client):
    item = await make(client)
    assert (await client.get(f"/internal/items/{item['id']}", headers=GW)).status_code == 403
    r = await client.get(f"/internal/items/{item['id']}", headers=SERVICE)
    assert r.status_code == 200 and r.json() == {
        "id": item["id"],
        "stock": 10,
        "price_cents": 1999,
    }
    assert (
        await client.post(f"/internal/items/{item['id']}/reserve", json={"quantity": 1}, headers=GW)
    ).status_code == 403


async def test_reserve_release_and_insufficient_stock(client):
    item = await make(client, stock=5)
    url = f"/internal/items/{item['id']}"
    r = await client.post(f"{url}/reserve", json={"quantity": 3}, headers=SERVICE)
    assert r.status_code == 200 and r.json()["stock"] == 2
    r = await client.post(f"{url}/reserve", json={"quantity": 3}, headers=SERVICE)
    assert r.status_code == 409
    r = await client.post(f"{url}/release", json={"quantity": 3}, headers=SERVICE)
    assert r.json()["stock"] == 5
    assert (
        await client.post("/internal/items/999/reserve", json={"quantity": 1}, headers=SERVICE)
    ).status_code == 404
    assert (
        await client.post("/internal/items/999/release", json={"quantity": 1}, headers=SERVICE)
    ).status_code == 404
    assert (
        await client.post(f"{url}/reserve", json={"quantity": 0}, headers=SERVICE)
    ).status_code == 422


async def test_concurrent_reservations_never_oversell(client):
    item = await make(client, stock=10)
    url = f"/internal/items/{item['id']}/reserve"
    results = await asyncio.gather(
        *(client.post(url, json={"quantity": 1}, headers=SERVICE) for _ in range(25))
    )
    assert sorted(r.status_code for r in results).count(200) == 10
    assert (await client.get(f"/internal/items/{item['id']}", headers=SERVICE)).json()["stock"] == 0
