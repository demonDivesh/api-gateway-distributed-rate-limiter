from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.catalog_client import (
    CatalogClient,
    CatalogUnavailable,
    InsufficientStock,
    ItemNotFound,
)
from app.config import Settings, get_settings
from app.database import create_engine, get_session, init_models
from app.deps import Caller, CurrentCaller
from app.models import Order
from app.schemas import OrderCreate, OrderList, OrderOut

logger = logging.getLogger("service")
Session = Annotated[AsyncSession, Depends(get_session)]


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        eng = engine or create_engine(settings.database_url)
        client = http_client or httpx.AsyncClient(timeout=settings.catalog_timeout_seconds)
        app.state.engine = eng
        app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
        app.state.catalog = CatalogClient(
            client,
            settings.catalog_url,
            settings.service_token,
            settings.catalog_retries,
        )
        await init_models(eng)
        yield
        if http_client is None:
            await client.aclose()
        if engine is None:
            await eng.dispose()

    app = FastAPI(title="Service B - Orders", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def instance_header(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Instance-Id"] = settings.instance_id
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "instance": settings.instance_id,
        }

    @app.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
    async def create_order(
        body: OrderCreate, request: Request, session: Session, caller: CurrentCaller
    ) -> Order:
        """Reserve stock in Service A, then persist the order (compensating on failure)."""
        catalog: CatalogClient = request.app.state.catalog
        rid = request.headers.get("x-request-id")
        try:
            stock = await catalog.reserve(body.item_id, body.quantity, rid)
        except ItemNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found") from None
        except InsufficientStock:
            raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock") from None
        except CatalogUnavailable:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Catalog service unavailable"
            ) from None

        order = Order(
            user_id=caller.user_id,
            item_id=body.item_id,
            quantity=body.quantity,
            unit_price_cents=stock.price_cents,
            total_cents=stock.price_cents * body.quantity,
        )
        try:
            session.add(order)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("order persistence failed; releasing reserved stock")
            try:
                await catalog.release(body.item_id, body.quantity, rid)
            except Exception:
                logger.exception(
                    "compensation failed for item %s qty %s",
                    body.item_id,
                    body.quantity,
                )
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create order"
            ) from None
        await session.refresh(order)
        return order

    def _visible(stmt, caller: Caller):  # type: ignore[no-untyped-def]
        return stmt if caller.is_admin else stmt.where(Order.user_id == caller.user_id)

    @app.get("/orders", response_model=OrderList)
    async def list_orders(
        session: Session,
        caller: CurrentCaller,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> OrderList:
        base = _visible(select(Order), caller)
        rows = (
            await session.scalars(base.order_by(Order.id.desc()).limit(limit).offset(offset))
        ).all()
        total = await session.scalar(_visible(select(func.count()).select_from(Order), caller)) or 0
        return OrderList(
            orders=[OrderOut.model_validate(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def _get(session: AsyncSession, order_id: int, caller: Caller) -> Order:
        order = await session.scalar(_visible(select(Order).where(Order.id == order_id), caller))
        if order is None:  # 404 (not 403) so users cannot probe for other users' order ids
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        return order

    @app.get("/orders/{order_id}", response_model=OrderOut)
    async def get_order(order_id: int, session: Session, caller: CurrentCaller) -> Order:
        return await _get(session, order_id, caller)

    @app.post("/orders/{order_id}/cancel", response_model=OrderOut)
    async def cancel_order(
        order_id: int, request: Request, session: Session, caller: CurrentCaller
    ) -> Order:
        order = await _get(session, order_id, caller)
        if order.status == "cancelled":
            raise HTTPException(status.HTTP_409_CONFLICT, "Order already cancelled")
        try:
            await request.app.state.catalog.release(
                order.item_id, order.quantity, request.headers.get("x-request-id")
            )
        except CatalogUnavailable:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Catalog service unavailable"
            ) from None
        order.status = "cancelled"
        await session.commit()
        await session.refresh(order)
        return order

    return app
