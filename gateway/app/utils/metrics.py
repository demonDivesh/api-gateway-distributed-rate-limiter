"""Prometheus metrics plus an in-memory summary for the dashboard."""

from __future__ import annotations

import time
from collections import Counter, deque

from prometheus_client import CollectorRegistry, Gauge, Histogram, generate_latest
from prometheus_client import Counter as PCounter
from prometheus_client.exposition import CONTENT_TYPE_LATEST

CONTENT_TYPE = CONTENT_TYPE_LATEST


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = PCounter(
            "gateway_http_requests_total",
            "HTTP requests handled",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "gateway_http_request_duration_seconds",
            "Request latency",
            ["route"],
            registry=self.registry,
        )
        self.rate_limit = PCounter(
            "gateway_rate_limit_decisions_total",
            "Rate limiter decisions",
            ["decision"],
            registry=self.registry,
        )
        self.upstream = PCounter(
            "gateway_upstream_requests_total",
            "Upstream requests",
            ["service", "outcome"],
            registry=self.registry,
        )
        self.breaker_state = Gauge(
            "gateway_circuit_breaker_state",
            "0=closed 1=half_open 2=open",
            ["service", "instance"],
            registry=self.registry,
        )
        self.instance_healthy = Gauge(
            "gateway_upstream_healthy",
            "1 if the instance passed its last health check",
            ["service", "instance"],
            registry=self.registry,
        )
        self.started_at = time.time()
        self._status: Counter[str] = Counter()
        self._decisions: Counter[str] = Counter()
        self._latencies: deque[float] = deque(maxlen=1000)
        self._total = 0

    def observe_request(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests.labels(method, route, str(status)).inc()
        self.latency.labels(route).observe(seconds)
        self._status[f"{status // 100}xx"] += 1
        self._latencies.append(seconds)
        self._total += 1

    def observe_rate_limit(self, decision: str) -> None:
        self.rate_limit.labels(decision).inc()
        self._decisions[decision] += 1

    def observe_upstream(self, service: str, outcome: str) -> None:
        self.upstream.labels(service, outcome).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)

    def summary(self) -> dict:
        lat = sorted(self._latencies)

        def pct(p: float) -> float:
            if not lat:
                return 0.0
            return round(lat[min(len(lat) - 1, int(len(lat) * p))] * 1000, 2)

        return {
            "uptime_seconds": int(time.time() - self.started_at),
            "total_requests": self._total,
            "status_classes": dict(self._status),
            "rate_limit": {
                "allowed": self._decisions["allowed"],
                "limited": self._decisions["limited"],
                "errors": self._decisions["error"],
            },
            "latency_ms": {
                "p50": pct(0.5),
                "p95": pct(0.95),
                "p99": pct(0.99),
                "samples": len(lat),
            },
        }
