import contextlib

from tests.conftest import ADMIN, GW, OTHER


async def order(client, headers=GW, item_id=1, quantity=2):
    return await client.post(
        "/orders", json={"item_id": item_id, "quantity": quantity}, headers=headers
    )


async def test_health_and_gateway_protection(client):
    assert (await client.get("/health")).json()["instance"] == "svc-b-test"
    assert (await client.get("/orders")).status_code == 401
    assert (
        await client.get("/orders", headers={**GW, "X-Gateway-Secret": "nope"})
    ).status_code == 401


async def test_create_order_reserves_stock_and_snapshots_price(client, catalog):
    r = await order(client, quantity=2)
    assert r.status_code == 201
    body = r.json()
    assert (body["unit_price_cents"], body["total_cents"], body["status"]) == (
        250,
        500,
        "confirmed",
    )
    assert body["user_id"] == "u-1"
    assert catalog.items[1]["stock"] == 3


async def test_order_errors_map_to_http_statuses(client, catalog):
    assert (await order(client, item_id=99)).status_code == 404
    assert (await order(client, quantity=6)).status_code == 409
    assert catalog.items[1]["stock"] == 5
    assert (
        await client.post("/orders", json={"item_id": 1, "quantity": 0}, headers=GW)
    ).status_code == 422
    assert (
        await client.post("/orders", json={"item_id": 0, "quantity": 1}, headers=GW)
    ).status_code == 422


async def test_catalog_outage_gives_503_and_creates_no_order(client, catalog):
    catalog.raise_connect = True
    assert (await order(client)).status_code == 503
    catalog.raise_connect = False
    assert (await client.get("/orders", headers=GW)).json()["total"] == 0
    catalog.fail_with = 500
    assert (await order(client)).status_code == 503


async def test_orders_are_scoped_to_their_owner(client):
    mine = (await order(client)).json()
    theirs = (await order(client, headers=OTHER)).json()
    assert [o["id"] for o in (await client.get("/orders", headers=GW)).json()["orders"]] == [
        mine["id"]
    ]
    assert (await client.get(f"/orders/{theirs['id']}", headers=GW)).status_code == 404
    assert (await client.get(f"/orders/{mine['id']}", headers=GW)).status_code == 200
    assert (await client.get("/orders", headers=ADMIN)).json()["total"] == 2
    assert (await client.get(f"/orders/{theirs['id']}", headers=ADMIN)).status_code == 200


async def test_cancel_releases_stock_once(client, catalog):
    o = (await order(client, quantity=4)).json()
    assert catalog.items[1]["stock"] == 1
    r = await client.post(f"/orders/{o['id']}/cancel", headers=GW)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert catalog.items[1]["stock"] == 5
    assert (await client.post(f"/orders/{o['id']}/cancel", headers=GW)).status_code == 409
    assert catalog.items[1]["stock"] == 5
    assert (await client.post(f"/orders/{o['id']}/cancel", headers=OTHER)).status_code == 404


async def test_catalog_reads_are_retried_but_reserve_is_not(client, catalog):
    from app.catalog_client import CatalogUnavailable

    catalog.raise_connect = True
    before = catalog.attempts
    await order(client)
    assert catalog.attempts - before == 1  # POST reserve: single attempt
    before = catalog.attempts
    with contextlib.suppress(CatalogUnavailable):
        await client.app.state.catalog.get_item(1)
    assert catalog.attempts - before == 3  # GET: 1 + 2 retries


async def test_persistence_failure_triggers_compensation(client, catalog, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    async def broken_commit(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(AsyncSession, "commit", broken_commit)
    r = await order(client, quantity=2)
    assert r.status_code == 500
    assert catalog.items[1]["stock"] == 5  # reserved stock was released again
    assert ("POST", "/internal/items/1/release") in catalog.calls


async def test_list_pagination(client):
    for _ in range(3):
        await order(client, quantity=1)
    r = await client.get("/orders?limit=2&offset=0", headers=GW)
    assert len(r.json()["orders"]) == 2 and r.json()["total"] == 3
    assert (await client.get("/orders?limit=0", headers=GW)).status_code == 422
