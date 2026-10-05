"""Service-to-service client for Service A (httpx, timeouts, retries on idempotent calls)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("service.catalog")


class CatalogUnavailable(Exception):
    """Service A could not be reached or answered with a 5xx."""


class ItemNotFound(Exception):
    pass


class InsufficientStock(Exception):
    pass


@dataclass(frozen=True)
class StockInfo:
    id: int
    stock: int
    price_cents: int


class CatalogClient:
    def __init__(
        self, client: httpx.AsyncClient, base_url: str, token: str, retries: int = 2
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._token = token
        self._retries = retries

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        request_id: str | None = None,
        idempotent: bool = False,
    ) -> httpx.Response:
        headers = {"X-Service-Token": self._token}
        if request_id:
            headers["X-Request-ID"] = request_id
        attempts = 1 + (self._retries if idempotent else 0)
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await self._client.request(
                    method, self._base + path, json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                last = exc
                logger.warning(
                    "catalog call failed (%s/%s): %s",
                    attempt + 1,
                    attempts,
                    type(exc).__name__,
                )
                continue
            if resp.status_code >= 500:
                last = CatalogUnavailable(f"catalog returned {resp.status_code}")
                continue
            return resp
        raise CatalogUnavailable(str(last) or "catalog unavailable") from last

    async def get_item(self, item_id: int, request_id: str | None = None) -> StockInfo:
        resp = await self._call(
            "GET", f"/internal/items/{item_id}", request_id=request_id, idempotent=True
        )
        if resp.status_code == 404:
            raise ItemNotFound(item_id)
        resp.raise_for_status()
        return StockInfo(**resp.json())

    async def reserve(
        self, item_id: int, quantity: int, request_id: str | None = None
    ) -> StockInfo:
        resp = await self._call(
            "POST",
            f"/internal/items/{item_id}/reserve",
            json={"quantity": quantity},
            request_id=request_id,
        )
        if resp.status_code == 404:
            raise ItemNotFound(item_id)
        if resp.status_code == 409:
            raise InsufficientStock(item_id)
        resp.raise_for_status()
        return StockInfo(**resp.json())

    async def release(self, item_id: int, quantity: int, request_id: str | None = None) -> None:
        resp = await self._call(
            "POST",
            f"/internal/items/{item_id}/release",
            json={"quantity": quantity},
            request_id=request_id,
        )
        if resp.status_code not in (200, 404):
            resp.raise_for_status()
