from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


# ── PurchaseOrder CRUD ────────────────────────────────────────────────────────

class POCreate(BaseModel):
    supplier: str
    sku: str
    qty_ordered: int
    qty_available: int
    unit_cost: Decimal
    po_number: str
    created_date: date
    notes: str | None = None


class POStatusUpdate(BaseModel):
    status: Literal["PENDING", "PAID", "CANCELLED"]


class PORead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier: str
    sku: str
    qty_ordered: int
    qty_available: int
    unit_cost: Decimal
    status: str
    po_number: str
    created_date: date
    paid_date: date | None
    notes: str | None


# ── Daily view ────────────────────────────────────────────────────────────────

class SKUItemOut(BaseModel):
    sku: str
    supplier: str
    ordered: int
    available: int
    unit_cost: float
    gap: int
    oversold: int
    avail_final: int
    total_cost: float
    oversold_value: float
    avail_value: float
    status: Literal["ok", "low", "exact", "oversold"]
    po_id: int
    po_status: str


class BalanceOut(BaseModel):
    starting_balance: float
    total_cost: float
    available_value: float
    oversold_value: float
    ending_balance: float


class PODailyResponse(BaseModel):
    date: str
    items: list[SKUItemOut]
    balance: BalanceOut
