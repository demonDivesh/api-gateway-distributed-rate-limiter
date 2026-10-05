"""Upstream pools with pluggable balancing strategies."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

from app.services.circuit_breaker import CircuitBreaker


@dataclass
class UpstreamInstance:
    url: str
    breaker: CircuitBreaker
    healthy: bool = True
    active_connections: int = 0
    last_check_at: float | None = None
    last_latency_ms: float | None = None
    last_error: str | None = None
    total_requests: int = 0

    @property
    def available(self) -> bool:
        return self.healthy and self.breaker.would_allow()

    def snapshot(self) -> dict:
        return {
            "url": self.url,
            "healthy": self.healthy,
            "active_connections": self.active_connections,
            "circuit_breaker": self.breaker.snapshot(),
            "last_check_at": self.last_check_at,
            "last_latency_ms": self.last_latency_ms,
            "last_error": self.last_error,
            "total_requests": self.total_requests,
        }


@dataclass
class UpstreamPool:
    name: str
    instances: list[UpstreamInstance]
    strategy: str = "round_robin"
    _counter: itertools.count = field(default_factory=itertools.count, repr=False)

    def select(self, exclude: set[str] | None = None) -> UpstreamInstance | None:
        exclude = exclude or set()
        candidates = [i for i in self.instances if i.available and i.url not in exclude]
        if not candidates:
            return None
        if self.strategy == "least_connections":
            lowest = min(i.active_connections for i in candidates)
            candidates = [i for i in candidates if i.active_connections == lowest]
            return candidates[next(self._counter) % len(candidates)]
        if self.strategy == "random":
            return random.choice(candidates)  # noqa: S311 - not security sensitive
        return candidates[next(self._counter) % len(candidates)]

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "strategy": self.strategy,
            "instances": [i.snapshot() for i in self.instances],
        }


class LoadBalancer:
    def __init__(self, pools: dict[str, UpstreamPool]) -> None:
        self.pools = pools

    def pool(self, name: str) -> UpstreamPool:
        return self.pools[name]

    def all_instances(self) -> list[tuple[str, UpstreamInstance]]:
        return [(p.name, i) for p in self.pools.values() for i in p.instances]

    def snapshot(self) -> list[dict]:
        return [p.snapshot() for p in self.pools.values()]
