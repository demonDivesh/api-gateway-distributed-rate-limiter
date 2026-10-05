import fakeredis

from tests.conftest import auth, login


async def test_anonymous_limited_by_ip_with_headers(app_factory):
    _, c = await app_factory(rate_limit_anonymous_per_minute=3)
    for expected_remaining in (2, 1, 0):
        r = await c.get("/api/service-a/x")  # 401 but still counted
        assert r.headers["x-ratelimit-limit"] == "3"
        assert r.headers["x-ratelimit-remaining"] == str(expected_remaining)
    r = await c.get("/api/service-a/x")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    assert r.headers["x-ratelimit-remaining"] == "0"
    assert r.headers["x-request-id"]


async def test_per_user_limits_are_independent(app_factory):
    _, c = await app_factory(rate_limit_user_per_minute=2)
    a = await c.post("/api/v1/auth/register", json={"username": "u1u1", "password": "password-1"})
    b = await c.post("/api/v1/auth/register", json={"username": "u2u2", "password": "password-2"})
    assert a.status_code == b.status_code == 201
    ta = (await login(c, "u1u1", "password-1"))["access_token"]
    tb = (await login(c, "u2u2", "password-2"))["access_token"]
    for _ in range(2):
        assert (await c.get("/api/service-a/x", headers=auth(ta))).status_code == 200
    assert (await c.get("/api/service-a/x", headers=auth(ta))).status_code == 429
    assert (await c.get("/api/service-a/x", headers=auth(tb))).status_code == 200


async def test_admin_gets_higher_limit(app_factory):
    _, c = await app_factory(rate_limit_user_per_minute=1, rate_limit_admin_per_minute=5)
    tok = (await login(c, "admin", "admin-pass-123"))["access_token"]
    codes = [(await c.get("/api/service-a/x", headers=auth(tok))).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


async def test_login_has_strict_limit(app_factory):
    _, c = await app_factory(rate_limit_auth_per_minute=3)
    codes = [
        (await c.post("/api/v1/auth/login", json={"username": "x", "password": "y"})).status_code
        for _ in range(5)
    ]
    assert codes == [401, 401, 401, 429, 429]


async def test_health_and_metrics_are_exempt(app_factory):
    _, c = await app_factory(rate_limit_anonymous_per_minute=1)
    for _ in range(5):
        assert (await c.get("/health")).status_code == 200
        assert "x-ratelimit-limit" not in (await c.get("/health")).headers


async def test_can_be_disabled(app_factory):
    _, c = await app_factory(rate_limit_enabled=False, rate_limit_anonymous_per_minute=1)
    for _ in range(5):
        r = await c.get("/api/service-a/x")
        assert r.status_code == 401 and "x-ratelimit-limit" not in r.headers


async def test_token_bucket_algorithm_selectable(app_factory):
    app, c = await app_factory(
        rate_limit_algorithm="token_bucket", rate_limit_anonymous_per_minute=2
    )
    assert app.state.rate_limiter.algorithm == "token_bucket"
    codes = [(await c.get("/api/service-a/x")).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


async def test_two_gateway_replicas_share_one_limit(app_factory):
    _, c1 = await app_factory(rate_limit_anonymous_per_minute=4)
    _, c2 = await app_factory(rate_limit_anonymous_per_minute=4)  # same fake Redis
    codes = []
    for i in range(6):
        codes.append((await (c1 if i % 2 == 0 else c2).get("/api/service-a/x")).status_code)
    assert codes.count(429) == 2


async def test_fail_open_when_redis_is_down(app_factory):
    app, c = await app_factory(rate_limit_fail_open=True)
    app.state.rate_limiter = _BrokenLimiter()
    assert (await c.get("/api/service-a/x")).status_code == 401  # request still served
    assert app.state.metrics.summary()["rate_limit"]["errors"] == 1


async def test_fail_closed_when_configured(app_factory):
    app, c = await app_factory(rate_limit_fail_open=False)
    app.state.rate_limiter = _BrokenLimiter()
    r = await c.get("/api/service-a/x")
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"


class _BrokenLimiter:
    algorithm = "sliding_window"

    async def check(self, *a, **kw):
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("redis down")


_ = fakeredis
