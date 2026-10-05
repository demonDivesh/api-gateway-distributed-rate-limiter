"""Async SQLAlchemy engine/session management."""

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
from sqlalchemy.pool import StaticPool

from app.models.base import Base

logger = logging.getLogger("gateway.database")


def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_async_engine(url, echo=echo, **kwargs)
    return create_async_engine(url, echo=echo, pool_pre_ping=True, pool_size=10, max_overflow=10)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def wait_for_database(engine: AsyncEngine, attempts: int = 30, delay: float = 1.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            logger.warning("database not ready (%s/%s): %s", attempt, attempts, exc)
            await asyncio.sleep(delay)
    raise RuntimeError("database did not become available")


async def init_models(engine: AsyncEngine) -> None:
    """Create tables. A Postgres advisory lock makes concurrent replicas safe."""
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        await conn.run_sync(Base.metadata.create_all)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
