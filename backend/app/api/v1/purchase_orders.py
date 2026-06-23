from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from generate_po import generate_po_pdf

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


class SupplierInfo(BaseModel):
    name: str = ""
    address: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""


class BuyerInfo(BaseModel):
    name: str = ""
    company: str = ""
    email: str = ""
    address: str = ""


class Balance(BaseModel):
    total_cost: float = 0
    available_value: float = 0
    oversold_value: float = 0
    starting_balance: float = 0
    ending_balance: float = 0


class GeneratePDFRequest(BaseModel):
    supplier: str
    po_number: str
    date: str
    items: list[dict[str, Any]]
    supplier_info: SupplierInfo
    buyer_info: BuyerInfo
    balance: Balance


@router.post("/generate-pdf")
async def generate_pdf(body: GeneratePDFRequest):
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.po_number)
    output_path = os.path.join(tempfile.gettempdir(), f"{safe_name}.pdf")

    generate_po_pdf(
        output_path=output_path,
        supplier=body.supplier,
        po_number=body.po_number,
        date=body.date,
        items=body.items,
        supplier_info=body.supplier_info.model_dump(),
        buyer_info=body.buyer_info.model_dump(),
        balance=body.balance.model_dump(),
    )

    return FileResponse(
        path=output_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}.pdf"'},
    )
