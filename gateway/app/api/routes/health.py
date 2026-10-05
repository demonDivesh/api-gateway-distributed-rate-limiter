from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.schemas.health import HealthOut, ReadinessOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def liveness() -> HealthOut:
    """Liveness: the process is up. Does not touch dependencies."""
    return HealthOut(status="ok")


@router.get("/health/ready", response_model=ReadinessOut)
async def readiness(request: Request) -> JSONResponse:
    """Readiness: Redis and PostgreSQL reachable, at least one instance per upstream pool."""
    state = request.app.state
    checks: dict[str, str] = {}
    try:
        await state.redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    try:
        async with state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    for pool in state.load_balancer.pools.values():
        up = sum(1 for i in pool.instances if i.available)
        checks[f"upstream:{pool.name}"] = "ok" if up else "no_healthy_instances"
    ready = all(v == "ok" for k, v in checks.items() if not k.startswith("upstream:"))
    body = ReadinessOut(status="ready" if ready else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if ready else 503, content=body.model_dump())


@router.get("/health/upstreams")
async def upstreams(request: Request) -> list[dict]:
    """Detailed state (health, breaker, connections) of every upstream instance."""
    return request.app.state.load_balancer.snapshot()  # type: ignore[no-any-return]
