"""Locust scenarios for the gateway.

    pip install locust
    locust -f load_test/locustfile.py --host http://localhost:8000
    # headless:
    locust -f load_test/locustfile.py --host http://localhost:8000 -u 50 -r 10 -t 1m --headless

Each simulated user registers its own account, so per-user rate limits apply per user.
Raise RATE_LIMIT_USER_PER_MINUTE on the gateway to measure raw throughput, or leave the
defaults to watch 429s appear (they are recorded as successes: rejection is the expected
behaviour, and the run summary reports them under their own name).
"""

from __future__ import annotations

import uuid

from locust import HttpUser, between, task


class ApiUser(HttpUser):
    wait_time = between(0.05, 0.4)
    headers: dict[str, str]
    item_id: int | None = None

    def on_start(self) -> None:
        name = f"load-{uuid.uuid4().hex[:10]}"
        password = "load-test-pass-123"
        self.client.post(
            "/api/v1/auth/register",
            json={"username": name, "password": password},
            name="register",
        )
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": name, "password": password},
            name="login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
                resp.success()
            else:
                resp.failure(f"login failed: {resp.status_code}")
                self.headers = {}
        r = self.client.post(
            "/api/service-a/items",
            json={"name": "load item", "price_cents": 100, "stock": 1_000_000},
            headers=self.headers,
            name="create item",
        )
        if r.status_code == 201:
            self.item_id = r.json()["id"]

    def _get(self, path: str, name: str) -> None:
        with self.client.get(path, headers=self.headers, name=name, catch_response=True) as resp:
            if resp.status_code == 429:
                resp.success()  # expected under load; visible in the 429 breakdown below
                resp.request_meta["name"] = f"{name} [429 limited]"
            elif resp.status_code >= 400:
                resp.failure(f"{resp.status_code}: {resp.text[:120]}")

    @task(6)
    def list_items(self) -> None:
        self._get("/api/service-a/items?limit=10", "GET items")

    @task(3)
    def whoami(self) -> None:
        self._get("/api/service-a/whoami", "GET whoami")

    @task(2)
    def place_and_list_orders(self) -> None:
        if self.item_id is None:
            return
        self.client.post(
            "/api/service-b/orders",
            json={"item_id": self.item_id, "quantity": 1},
            headers=self.headers,
            name="POST order",
        )
        self._get("/api/service-b/orders", "GET orders")

    @task(1)
    def unauthenticated(self) -> None:
        with self.client.get(
            "/api/service-a/items", name="anonymous (expect 401)", catch_response=True
        ) as resp:
            if resp.status_code in (401, 429):
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}")
