"""
Generate a supplier Invoice PDF using reportlab.
Called by the FastAPI endpoint in app/api/v1/suppliers.py.
Mirrors the styling of generate_po.py for a consistent look.
"""
from __future__ import annotations

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
_GRAY  = colors.HexColor("#6B7280")
_LIGHT = colors.HexColor("#F9FAFB")


def _fmt(n: float) -> str:
    return f"${n:,.2f}"


def generate_invoice_pdf(
    output_path: str,
    invoice_number: str,
    period: str,
    status: str,
    supplier_info: dict[str, str],
    buyer_info: dict[str, str],
    line_items: list[dict[str, Any]],
    total_amount: float,
) -> None:
    """Write an invoice PDF to *output_path*."""

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
        para("<b>INVOICE</b>", fontSize=18, textColor=_BLUE),
        para(
            f"<b>Invoice #:</b> {invoice_number}<br/>"
            f"<b>Period:</b> {period}<br/>"
            f"<b>Status:</b> {status.upper()}",
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

    # ── From (Supplier) / To (Buyer) ─────────────────────────────────────────
    addr_data = [[
        para(
            f"<b>FROM (Supplier)</b><br/>"
            f"{supplier_info.get('name','')}<br/>"
            f"{supplier_info.get('address','')}<br/>"
            f"{supplier_info.get('city','')}<br/>"
            f"{supplier_info.get('email','')}",
            fontSize=8.5,
            leading=13,
        ),
        para(
            f"<b>BILL TO (Buyer)</b><br/>"
            f"{buyer_info.get('name','')}<br/>"
            f"{buyer_info.get('company','')}<br/>"
            f"{buyer_info.get('address','')}",
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

    # ── Line items ───────────────────────────────────────────────────────────
    col_labels = ["Description", "Qty", "Unit $", "Total"]
    col_widths = [4.6 * inch, 0.7 * inch, 0.85 * inch, 0.85 * inch]

    header_row = [para(f"<b>{c}</b>", fontSize=8, textColor=colors.white) for c in col_labels]
    table_data = [header_row]

    for it in line_items:
        qty = it.get("quantity", 0)
        unit = float(it.get("unit_amount", 0) or 0)
        tot = float(it.get("total_amount", 0) or 0)
        table_data.append([
            para(str(it.get("description", "")), fontSize=8),
            para(str(qty), fontSize=8, alignment=1),
            para(_fmt(unit), fontSize=8, alignment=2),
            para(_fmt(tot), fontSize=8, alignment=2),
        ])

    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",   (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 1), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 14))

    # ── Total ─────────────────────────────────────────────────────────────────
    totals_table = Table(
        [[para("<b>Total Due</b>", fontSize=10, textColor=_GREEN),
          para(f"<b>{_fmt(total_amount)}</b>", fontSize=10, alignment=2, textColor=_GREEN)]],
        colWidths=[5.5 * inch, 1.5 * inch],
    )
    totals_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 0), (-1, 0), 1, _BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)

    doc.build(story)
