from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.database import create_engine, get_session, init_models
from app.deps import CurrentCaller, service_caller
from app.models import Item
from app.schemas import (
    ItemCreate,
    ItemList,
    ItemOut,
    ItemUpdate,
    StockChange,
    StockOut,
    WhoAmI,
)

Session = Annotated[AsyncSession, Depends(get_session)]


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        eng = engine or create_engine(settings.database_url)
        app.state.engine = eng
        app.state.session_factory = async_sessionmaker(eng, expire_on_commit=False)
        await init_models(eng)
        yield
        if engine is None:
            await eng.dispose()

    app = FastAPI(title="Service A - Catalog", version="1.0.0", lifespan=lifespan)
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

    @app.get("/whoami", response_model=WhoAmI)
    async def whoami(request: Request, caller: CurrentCaller) -> WhoAmI:
        return WhoAmI(
            service=settings.service_name,
            instance=settings.instance_id,
            user_id=caller.user_id,
            user_name=caller.username,
            role=caller.role,
            request_id=request.headers.get("x-request-id"),
        )

    @app.get("/items", response_model=ItemList)
    async def list_items(
        session: Session,
        _: CurrentCaller,
        q: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ItemList:
        stmt = select(Item)
        count = select(func.count()).select_from(Item)
        if q:
            pattern = f"%{q.lower()}%"
            stmt = stmt.where(func.lower(Item.name).like(pattern))
            count = count.where(func.lower(Item.name).like(pattern))
        rows = (await session.scalars(stmt.order_by(Item.id).limit(limit).offset(offset))).all()
        total = await session.scalar(count) or 0
        return ItemList(
            items=[ItemOut.model_validate(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
    async def create_item(body: ItemCreate, session: Session, caller: CurrentCaller) -> Item:
        item = Item(**body.model_dump(), owner_id=caller.user_id)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item

    async def _get(session: AsyncSession, item_id: int) -> Item:
        item = await session.get(Item, item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        return item

    @app.get("/items/{item_id}", response_model=ItemOut)
    async def get_item(item_id: int, session: Session, _: CurrentCaller) -> Item:
        return await _get(session, item_id)

    @app.patch("/items/{item_id}", response_model=ItemOut)
    async def update_item(
        item_id: int, body: ItemUpdate, session: Session, caller: CurrentCaller
    ) -> Item:
        item = await _get(session, item_id)
        if item.owner_id != caller.user_id and not caller.is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only the owner or an admin can modify this item",
            )
        for field, value in body.model_dump(exclude_unset=True).items():
            if value is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} cannot be null"
                )
            setattr(item, field, value)
        await session.commit()
        await session.refresh(item)
        return item

    @app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: int, session: Session, caller: CurrentCaller) -> Response:
        item = await _get(session, item_id)
        if item.owner_id != caller.user_id and not caller.is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only the owner or an admin can delete this item",
            )
        await session.delete(item)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ---- internal endpoints used by Service B (service token, not exposed to users) ----
    @app.get(
        "/internal/items/{item_id}",
        response_model=StockOut,
        dependencies=[Depends(service_caller)],
    )
    async def internal_get(item_id: int, session: Session) -> StockOut:
        item = await _get(session, item_id)
        return StockOut(id=item.id, stock=item.stock, price_cents=item.price_cents)

    @app.post(
        "/internal/items/{item_id}/reserve",
        response_model=StockOut,
        dependencies=[Depends(service_caller)],
    )
    async def reserve(item_id: int, body: StockChange, session: Session) -> StockOut:
        """Atomically decrement stock; the WHERE clause prevents overselling under concurrency."""
        result = await session.execute(
            update(Item)
            .where(Item.id == item_id, Item.stock >= body.quantity)
            .values(stock=Item.stock - body.quantity)
        )
        await session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            await _get(session, item_id)  # 404 if missing
            raise HTTPException(status.HTTP_409_CONFLICT, "Insufficient stock")
        item = await _get(session, item_id)
        await session.refresh(item)
        return StockOut(id=item.id, stock=item.stock, price_cents=item.price_cents)

    @app.post(
        "/internal/items/{item_id}/release",
        response_model=StockOut,
        dependencies=[Depends(service_caller)],
    )
    async def release(item_id: int, body: StockChange, session: Session) -> StockOut:
        result = await session.execute(
            update(Item).where(Item.id == item_id).values(stock=Item.stock + body.quantity)
        )
        await session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        item = await _get(session, item_id)
        await session.refresh(item)
        return StockOut(id=item.id, stock=item.stock, price_cents=item.price_cents)

    return app
