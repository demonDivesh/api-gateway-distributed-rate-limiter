from app.utils.metrics import Metrics


def test_summary_and_render():
    m = Metrics()
    for i in range(10):
        m.observe_request("GET", "/x", 200 if i < 8 else 500, 0.01 * (i + 1))
    m.observe_rate_limit("allowed")
    m.observe_rate_limit("limited")
    m.observe_upstream("service-a", "success")
    s = m.summary()
    assert s["total_requests"] == 10
    assert s["status_classes"] == {"2xx": 8, "5xx": 2}
    assert s["rate_limit"]["limited"] == 1
    assert s["latency_ms"]["p50"] > 0
    text = m.render().decode()
    assert "gateway_http_requests_total" in text and "gateway_rate_limit_decisions_total" in text


def test_empty_summary():
    assert Metrics().summary()["latency_ms"]["p99"] == 0.0
