from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1000)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    item_id: int
    quantity: int
    unit_price_cents: int
    total_cents: int
    status: str
    created_at: datetime


class OrderList(BaseModel):
    orders: list[OrderOut]
    total: int
    limit: int
    offset: int
