"""
Generate a Purchase Order PDF using reportlab.
Called by the FastAPI endpoint in app/api/v1/purchase_orders.py.
"""
from __future__ import annotations

import os
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
)


_BLUE  = colors.HexColor("#2563EB")
_GREEN = colors.HexColor("#15803D")
_RED   = colors.HexColor("#DC2626")
_GRAY  = colors.HexColor("#6B7280")
_LIGHT = colors.HexColor("#F9FAFB")
_AMBER = colors.HexColor("#D97706")


def _fmt(n: float) -> str:
    return f"${n:,.2f}"


def generate_po_pdf(
    output_path: str,
    supplier: str,
    po_number: str,
    date: str,
    items: list[dict[str, Any]],
    supplier_info: dict[str, str],
    buyer_info: dict[str, str],
    balance: dict[str, float],
) -> None:
    """Write a PO PDF to *output_path*."""

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]

    def para(text: str, **kw) -> Paragraph:
        style = ParagraphStyle("_tmp", parent=normal, **kw)
        return Paragraph(text, style)

    story: list[Any] = []

    # ── Header ──────────────────────────────────────────────────────────────
    header_data = [[
        para("<b>PURCHASE ORDER</b>", fontSize=18, textColor=_BLUE),
        para(
            f"<b>PO #:</b> {po_number}<br/>"
            f"<b>Date:</b> {date}<br/>"
            f"<b>Supplier:</b> {supplier}",
            fontSize=9,
            alignment=2,
        ),
    ]]
    header_table = Table(header_data, colWidths=[4 * inch, 3 * inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1.5, color=_BLUE, spaceAfter=10))

    # ── From / To addresses ─────────────────────────────────────────────────
    addr_data = [[
        para(
            f"<b>FROM (Buyer)</b><br/>"
            f"{buyer_info.get('name','')}<br/>"
            f"{buyer_info.get('company','')}<br/>"
            f"{buyer_info.get('address','')}<br/>"
            f"{buyer_info.get('email','')}",
            fontSize=8.5,
            leading=13,
        ),
        para(
            f"<b>TO (Supplier)</b><br/>"
            f"{supplier_info.get('name','')}<br/>"
            f"{supplier_info.get('address','')}<br/>"
            f"{supplier_info.get('city','')}",
            fontSize=8.5,
            leading=13,
        ),
    ]]
    addr_table = Table(addr_data, colWidths=[3.5 * inch, 3.5 * inch])
    addr_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
        ("BOX", (0, 0), (0, 0), 0.5, colors.lightgrey),
        ("BOX", (1, 0), (1, 0), 0.5, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(addr_table)
    story.append(Spacer(1, 14))

    # ── SKU Table ────────────────────────────────────────────────────────────
    col_labels = ["Item", "Ordered", "Available", "Gap", "Oversold", "Unit $", "Total", "Status"]
    col_widths = [2.2*inch, 0.65*inch, 0.75*inch, 0.55*inch, 0.7*inch, 0.6*inch, 0.7*inch, 0.65*inch]

    header_row = [para(f"<b>{c}</b>", fontSize=8, textColor=colors.white) for c in col_labels]
    table_data = [header_row]

    STATUS_COLORS = {
        "ok":       (_GREEN, "OK"),
        "low":      (_AMBER, None),
        "exact":    (_AMBER, "Exact"),
        "oversold": (_RED,   None),
    }

    row_bg: list[tuple[int, colors.Color]] = []

    for row_idx, item in enumerate(items, start=1):
        gap: int = item.get("gap", 0)
        oversold: int = item.get("oversold", 0)
        status: str = item.get("status", "ok")

        gap_str = f"+{gap}" if gap > 0 else str(gap)
        oversold_str = str(oversold) if gap < 0 else "—"
        avail_str = str(max(0, item.get("avail_final", 0)))

        color, label = STATUS_COLORS.get(status, (_GRAY, status))
        if label is None:
            label = f"Low +{gap}" if status == "low" else f"Oversold {oversold}"
        status_para = para(label, fontSize=7.5, textColor=color)

        table_data.append([
            para(item.get("sku", ""), fontSize=8),
            para(str(item.get("ordered", 0)), fontSize=8, alignment=1),
            para(avail_str, fontSize=8, alignment=1),
            para(gap_str, fontSize=8, alignment=1,
                 textColor=_RED if gap < 0 else (_AMBER if gap == 0 else _GREEN)),
            para(oversold_str, fontSize=8, alignment=1,
                 textColor=_RED if gap < 0 else _GRAY),
            para(_fmt(item.get("unit_cost", 0)), fontSize=8, alignment=2),
            para(_fmt(item.get("total_cost", 0)), fontSize=8, alignment=2),
            status_para,
        ])

        if status == "oversold":
            row_bg.append((row_idx, colors.HexColor("#FEF2F2")))
        elif status == "exact":
            row_bg.append((row_idx, colors.HexColor("#FFFBEB")))
        elif row_idx % 2 == 0:
            row_bg.append((row_idx, _LIGHT))

    sku_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",   (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 1), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for row_idx, bg in row_bg:
        ts.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))

    sku_table.setStyle(TableStyle(ts))
    story.append(sku_table)
    story.append(Spacer(1, 14))

    # ── Totals ───────────────────────────────────────────────────────────────
    total_cost     = balance.get("total_cost", 0)
    oversold_value = balance.get("oversold_value", 0)
    balance_due    = total_cost - oversold_value

    totals_rows: list[list[Any]] = [
        [para("Subtotal", fontSize=9), para(_fmt(total_cost), fontSize=9, alignment=2)],
    ]
    if oversold_value > 0:
        totals_rows.append([
            para("Oversold A/R (deducted)", fontSize=9, textColor=_RED),
            para(f"−{_fmt(oversold_value)}", fontSize=9, alignment=2, textColor=_RED),
        ])
    totals_rows.append([
        para("<b>Balance Due</b>", fontSize=10, textColor=_GREEN),
        para(f"<b>{_fmt(balance_due)}</b>", fontSize=10, alignment=2, textColor=_GREEN),
    ])

    totals_table = Table(totals_rows, colWidths=[5.5 * inch, 1.5 * inch])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, _BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 20))

    # ── Remittance slip ──────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRAY,
                            dash=(4, 3), spaceAfter=8))
    story.append(para("<i>Remittance Slip — detach and return with payment</i>",
                      fontSize=8, textColor=_GRAY))
    story.append(Spacer(1, 4))

    rem_data = [[
        para(
            f"<b>{supplier_info.get('name','')}</b><br/>"
            f"{supplier_info.get('address','')}<br/>"
            f"{supplier_info.get('city','')}",
            fontSize=8.5,
            leading=12,
        ),
        para(
            f"PO #: <b>{po_number}</b><br/>"
            f"Date: {date}",
            fontSize=8.5,
            leading=12,
            alignment=1,
        ),
        para(
            f"<b>Balance Due</b><br/><font size=12 color='#15803D'><b>{_fmt(balance_due)}</b></font>",
            fontSize=8.5,
            leading=14,
            alignment=2,
        ),
    ]]
    rem_table = Table(rem_data, colWidths=[2.8 * inch, 2.4 * inch, 1.8 * inch])
    rem_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
    ]))
    story.append(rem_table)

    doc.build(story)
