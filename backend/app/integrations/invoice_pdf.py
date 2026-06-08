"""Generate purchase-order / invoice PDF using reportlab."""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_send_order_pdf(
    invoice_number: str,
    invoice_date: datetime,
    supplier_name: str,
    supplier_email: str | None,
    order_items: list[dict],
    total_amount: float,
    notes: str | None = None,
) -> bytes:
    """Return PDF bytes for a purchase-order sent to a supplier.

    order_items: list of dicts with keys:
      order_id, external_order_id (optional), catalog_name, sku (optional),
      quantity, unit_cost, total
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "po_title", parent=styles["Title"], fontSize=18, spaceAfter=3 * mm,
        textColor=colors.HexColor("#1e40af"),
    )
    info_style = ParagraphStyle(
        "po_info", parent=styles["Normal"], fontSize=10, spaceAfter=1.5 * mm,
    )
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    mono_style = ParagraphStyle("mono", parent=styles["Normal"], fontName="Courier", fontSize=8, leading=10)
    total_label_style = ParagraphStyle("total_label", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold", alignment=2)
    total_value_style = ParagraphStyle("total_value", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold", alignment=2)

    elements: list = []

    # ── Header ──────────────────────────────────────────────────────────────
    elements.append(Paragraph("PURCHASE ORDER", title_style))
    elements.append(Paragraph(f"<b>Reference:</b> {invoice_number}", info_style))
    elements.append(Paragraph(f"<b>Date:</b> {invoice_date.strftime('%B %d, %Y')}", info_style))
    elements.append(Paragraph(f"<b>Supplier:</b> {supplier_name}", info_style))
    if supplier_email:
        elements.append(Paragraph(f"<b>Email:</b> {supplier_email}", info_style))
    elements.append(Spacer(1, 6 * mm))

    # ── Items table ──────────────────────────────────────────────────────────
    col_widths = [22 * mm, 70 * mm, 28 * mm, 12 * mm, 22 * mm, 22 * mm]
    hdr_style = ParagraphStyle("hdr", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold", textColor=colors.white, alignment=0)

    rows: list = [[
        Paragraph("Order", hdr_style),
        Paragraph("Item", hdr_style),
        Paragraph("SKU", hdr_style),
        Paragraph("Qty", hdr_style),
        Paragraph("Unit Cost", hdr_style),
        Paragraph("Total", hdr_style),
    ]]

    for it in order_items:
        order_label = f"#{it['order_id']}"
        if it.get("external_order_id"):
            order_label += f"\n{it['external_order_id']}"
        rows.append([
            Paragraph(order_label, cell_style),
            Paragraph(str(it["catalog_name"]), cell_style),
            Paragraph(str(it.get("sku") or "—"), mono_style),
            Paragraph(str(it["quantity"]), ParagraphStyle("qty", parent=cell_style, alignment=2)),
            Paragraph(f"${it['unit_cost']:.2f}", ParagraphStyle("amt", parent=cell_style, alignment=2)),
            Paragraph(f"${it['total']:.2f}", ParagraphStyle("amt", parent=cell_style, alignment=2)),
        ])

    # Grand total row
    rows.append([
        "", "", "", "",
        Paragraph("TOTAL", total_label_style),
        Paragraph(f"${total_amount:.2f}", total_value_style),
    ])

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f0f4ff")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eff6ff")),
        ("GRID", (0, 0), (-1, -2), 0.4, colors.HexColor("#d1d5db")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#1e40af")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("NOSPLIT", (0, 0), (-1, -1)),
    ]))
    elements.append(table)

    if notes:
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph(f"<b>Notes:</b> {notes}", info_style))

    doc.build(elements)
    return buf.getvalue()
