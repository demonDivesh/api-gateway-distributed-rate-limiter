"""Active health checks for every upstream instance."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import httpx

from app.services.load_balancer import LoadBalancer, UpstreamInstance

logger = logging.getLogger("gateway.health")


class HealthChecker:
    def __init__(
        self,
        client: httpx.AsyncClient,
        balancer: LoadBalancer,
        interval: float = 5.0,
        timeout: float = 2.0,
        path: str = "/health",
    ) -> None:
        self._client = client
        self._balancer = balancer
        self._interval = interval
        self._timeout = timeout
        self._path = path
        self._task: asyncio.Task[None] | None = None

    async def check_instance(self, instance: UpstreamInstance) -> bool:
        started = time.perf_counter()
        error: str | None = None
        healthy = False
        try:
            resp = await self._client.get(instance.url + self._path, timeout=self._timeout)
            healthy = resp.status_code == 200
            if not healthy:
                error = f"status {resp.status_code}"
        except httpx.HTTPError as exc:
            error = type(exc).__name__
        if healthy != instance.healthy:
            logger.warning(
                "upstream health changed",
                extra={"upstream": instance.url, "healthy": healthy, "error": error},
            )
        instance.healthy = healthy
        instance.last_error = error
        instance.last_check_at = time.time()
        instance.last_latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return healthy

    async def check_all(self) -> None:
        await asyncio.gather(*(self.check_instance(i) for _, i in self._balancer.all_instances()))

    async def _run(self) -> None:
        while True:
            try:
                await self.check_all()
            except Exception:
                logger.exception("health check cycle failed")
            await asyncio.sleep(self._interval)

    async def start(self) -> None:
        await self.check_all()  # know the state before serving traffic
        self._task = asyncio.create_task(self._run(), name="health-checker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
