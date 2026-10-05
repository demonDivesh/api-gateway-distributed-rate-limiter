from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("service")


class Base(DeclarativeBase):
    pass


def create_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_async_engine(url, **kwargs)
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


async def init_models(engine: AsyncEngine, attempts: int = 30, delay: float = 1.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                if conn.dialect.name == "postgresql":
                    await conn.execute(text("SELECT pg_advisory_xact_lock(727275)"))
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:
            logger.warning("database not ready (%s/%s): %s", attempt, attempts, exc)
            if attempt == attempts:
                raise
            await asyncio.sleep(delay)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
