import time

import jwt
import pytest
from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.services.proxy_service import validate_path

SECRET = "unit-test-secret-unit-test-secret"


def token(**kw):
    args = {
        "user_id": "u1",
        "username": "bob",
        "role": "user",
        "token_type": "access",
        "secret": SECRET,
        "algorithm": "HS256",
        "ttl_seconds": 60,
    }
    args.update(kw)
    return create_token(**args)


def test_password_hash_roundtrip_and_salting():
    h1, h2 = hash_password("s3cret-pass"), hash_password("s3cret-pass")
    assert h1 != h2
    assert verify_password("s3cret-pass", h1)
    assert not verify_password("wrong", h1)
    assert not verify_password("x", "garbage")
    assert not verify_password("x", "bcrypt$a$b")


def test_token_roundtrip():
    claims = decode_token(token(), secret=SECRET, algorithm="HS256", expected_type="access")
    assert (claims.subject, claims.username, claims.role) == ("u1", "bob", "user")


def test_wrong_type_rejected():
    with pytest.raises(AuthenticationError):
        decode_token(
            token(token_type="refresh"), secret=SECRET, algorithm="HS256", expected_type="access"
        )


def test_expired_and_tampered_rejected():
    with pytest.raises(AuthenticationError, match="expired"):
        decode_token(
            token(ttl_seconds=-5), secret=SECRET, algorithm="HS256", expected_type="access"
        )
    with pytest.raises(AuthenticationError):
        decode_token(
            token(),
            secret="other-secret-other-secret-other-secret",
            algorithm="HS256",
            expected_type="access",
        )
    with pytest.raises(AuthenticationError):
        decode_token(token()[:-3] + "abc", secret=SECRET, algorithm="HS256", expected_type="access")


def test_alg_none_rejected():
    forged = jwt.encode(
        {"sub": "x", "exp": int(time.time()) + 60, "iat": 1, "jti": "j", "type": "access"},
        None,
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_token(forged, secret=SECRET, algorithm="HS256", expected_type="access")


def test_missing_required_claims_rejected():
    bare = jwt.encode({"sub": "x"}, SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_token(bare, secret=SECRET, algorithm="HS256", expected_type="access")


@pytest.mark.parametrize(
    "path,raw",
    [
        ("/api/a/../etc", None),
        ("/api/a/%2e%2e/x", b"/api/a/%2e%2e/x"),
        ("/api/a/x\\y", None),
        ("/api/a/x\x00", None),
        ("/api/a/%2F", b"/api/a/%2F"),
    ],
)
def test_bad_paths_rejected(path, raw):
    with pytest.raises(BadRequestError):
        validate_path(path, raw)


def test_good_path_accepted():
    validate_path("/api/service-a/items/42", b"/api/service-a/items/42?x=1")
