import time

import jwt

from tests.conftest import auth, login


async def test_register_login_me(gateway):
    _, c = gateway
    r = await c.post("/api/v1/auth/register", json={"username": "bob", "password": "bob-pass-123"})
    assert r.status_code == 201
    assert r.json()["role"] == "user" and "password" not in r.text
    tokens = await login(c, "bob", "bob-pass-123")
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == 900
    me = await c.get("/api/v1/auth/me", headers=auth(tokens["access_token"]))
    assert me.status_code == 200 and me.json()["username"] == "bob"


async def test_duplicate_username_conflict_case_insensitive(gateway):
    _, c = gateway
    body = {"username": "Carol", "password": "carol-pass-1"}
    assert (await c.post("/api/v1/auth/register", json=body)).status_code == 201
    r = await c.post("/api/v1/auth/register", json={**body, "username": "carol"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


async def test_registration_validation(gateway):
    _, c = gateway
    r = await c.post("/api/v1/auth/register", json={"username": "a", "password": "short"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and err["request_id"]
    assert {d["loc"][-1] for d in err["details"]} == {"username", "password"}
    r = await c.post(
        "/api/v1/auth/register", json={"username": "bad name!", "password": "long-enough-pw"}
    )
    assert r.status_code == 422


async def test_bad_credentials_uniform_error(gateway):
    _, c = gateway
    unknown = await c.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "whatever1"}
    )
    wrong = await c.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


async def test_registration_can_be_disabled(app_factory):
    _, c = await app_factory(allow_registration=False)
    r = await c.post(
        "/api/v1/auth/register", json={"username": "dave", "password": "dave-pass-123"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


async def test_me_requires_valid_token(gateway):
    app, c = gateway
    assert (await c.get("/api/v1/auth/me")).status_code == 401
    assert (await c.get("/api/v1/auth/me", headers=auth("garbage"))).status_code == 401
    expired = jwt.encode(
        {"sub": "x", "jti": "j1", "iat": 1, "exp": int(time.time()) - 10, "type": "access"},
        app.state.settings.jwt_secret,
        algorithm="HS256",
    )
    r = await c.get("/api/v1/auth/me", headers=auth(expired))
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]


async def test_refresh_rotates_and_old_token_is_revoked(gateway):
    _, c = gateway
    tokens = await login(c, "admin", "admin-pass-123")
    r1 = await c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    r2 = await c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401
    assert (
        await c.get("/api/v1/auth/me", headers=auth(r1.json()["access_token"]))
    ).status_code == 200


async def test_access_token_cannot_be_used_as_refresh(gateway):
    _, c = gateway
    tokens = await login(c, "admin", "admin-pass-123")
    r = await c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


async def test_logout_revokes_access_and_refresh(gateway):
    _, c = gateway
    tokens = await login(c, "admin", "admin-pass-123")
    r = await c.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=auth(tokens["access_token"]),
    )
    assert r.status_code == 204
    assert (await c.get("/api/v1/auth/me", headers=auth(tokens["access_token"]))).status_code == 401
    assert (
        await c.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401


async def test_auth_responses_are_not_cacheable(gateway):
    _, c = gateway
    r = await c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    assert r.headers["cache-control"] == "no-store"
