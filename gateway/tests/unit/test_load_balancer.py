from collections import Counter

from app.services.circuit_breaker import CircuitBreaker
from app.services.load_balancer import LoadBalancer, UpstreamInstance, UpstreamPool


def pool(strategy="round_robin", n=3) -> UpstreamPool:
    return UpstreamPool(
        "svc", [UpstreamInstance(f"http://i{i}", CircuitBreaker()) for i in range(n)], strategy
    )


def test_round_robin_distributes_evenly():
    p = pool()
    picks = Counter(p.select().url for _ in range(300))
    assert set(picks.values()) == {100}


def test_skips_unhealthy_instances():
    p = pool()
    p.instances[1].healthy = False
    assert {p.select().url for _ in range(20)} == {"http://i0", "http://i2"}


def test_skips_open_breakers():
    p = pool()
    for _ in range(5):
        p.instances[0].breaker.record_failure()
    assert "http://i0" not in {p.select().url for _ in range(20)}


def test_exclude_and_exhaustion():
    p = pool(n=2)
    assert p.select(exclude={"http://i0"}).url == "http://i1"
    assert p.select(exclude={"http://i0", "http://i1"}) is None


def test_least_connections_prefers_idle_instance():
    p = pool("least_connections")
    p.instances[0].active_connections = 5
    p.instances[1].active_connections = 2
    p.instances[2].active_connections = 9
    assert p.select().url == "http://i1"


def test_least_connections_ties_rotate():
    p = pool("least_connections")
    assert {p.select().url for _ in range(9)} == {"http://i0", "http://i1", "http://i2"}


def test_random_only_returns_available():
    p = pool("random")
    p.instances[0].healthy = False
    assert {p.select().url for _ in range(50)} <= {"http://i1", "http://i2"}


def test_snapshot_shape():
    lb = LoadBalancer({"svc": pool()})
    snap = lb.snapshot()
    assert snap[0]["name"] == "svc" and len(snap[0]["instances"]) == 3
    assert len(lb.all_instances()) == 3
