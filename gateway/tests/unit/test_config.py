import pytest
from app.core.config import Settings
from pydantic import ValidationError


def test_route_parsing_and_defaults():
    s = Settings(service_a_urls="http://a:1, http://b:2 ,", service_b_urls="http://c:3")
    routes = {r.name: r for r in s.routes}
    assert routes["service-a"].upstreams == ["http://a:1", "http://b:2"]
    assert routes["service-b"].prefix == "/api/service-b"


def test_short_jwt_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(jwt_secret="short")


def test_production_rejects_default_secrets():
    with pytest.raises(RuntimeError):
        Settings(environment="production").validate_for_production()
    Settings(
        environment="production",
        jwt_secret="x" * 40,
        admin_password="strong-admin-pw-1",
        internal_secret="y" * 40,
    ).validate_for_production()


def test_cors_origins_split():
    assert Settings(cors_origins="http://a, http://b").cors_origin_list == ["http://a", "http://b"]
