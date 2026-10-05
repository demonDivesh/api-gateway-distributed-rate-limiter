from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.deps import CurrentClaims
from app.core.exceptions import AuthenticationError
from app.core.security import constant_time_equals
from app.utils.metrics import CONTENT_TYPE

router = APIRouter(tags=["metrics"])

_STATE_VALUE = {"closed": 0, "half_open": 1, "open": 2}


def _refresh_gauges(request: Request) -> None:
    state = request.app.state
    for service, instance in state.load_balancer.all_instances():
        state.metrics.breaker_state.labels(service, instance.url).set(
            _STATE_VALUE[instance.breaker.state.value]
        )
        state.metrics.instance_healthy.labels(service, instance.url).set(
            1 if instance.healthy else 0
        )


@router.get("/metrics", include_in_schema=False)
async def prometheus(request: Request) -> Response:
    token = request.app.state.settings.metrics_token
    if token:
        header = request.headers.get("authorization", "")
        if not (header.lower().startswith("bearer ") and constant_time_equals(header[7:], token)):
            raise AuthenticationError("Metrics token required")
    _refresh_gauges(request)
    return Response(request.app.state.metrics.render(), media_type=CONTENT_TYPE)


@router.get("/api/v1/metrics/summary")
async def summary(request: Request, claims: CurrentClaims) -> dict:
    state = request.app.state
    return {
        **state.metrics.summary(),
        "upstreams": state.load_balancer.snapshot(),
        "rate_limit_config": {
            "algorithm": state.rate_limiter.algorithm,
            "anonymous_per_minute": state.settings.rate_limit_anonymous_per_minute,
            "user_per_minute": state.settings.rate_limit_user_per_minute,
            "admin_per_minute": state.settings.rate_limit_admin_per_minute,
            "auth_per_minute": state.settings.rate_limit_auth_per_minute,
        },
    }
