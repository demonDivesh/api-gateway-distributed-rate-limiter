from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    price_cents: int = Field(ge=0, le=100_000_000)
    stock: int = Field(default=0, ge=0, le=1_000_000)


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    price_cents: int
    stock: int
    owner_id: str
    created_at: datetime
    updated_at: datetime


class ItemList(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


class StockChange(BaseModel):
    quantity: int = Field(gt=0, le=10_000)


class StockOut(BaseModel):
    id: int
    stock: int
    price_cents: int


class WhoAmI(BaseModel):
    service: str
    instance: str
    user_id: str
    user_name: str
    role: str
    request_id: str | None
