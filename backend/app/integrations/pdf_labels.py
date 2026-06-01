"""
Build a combined "batch" shipping-label PDF for suppliers.

For each label we emit the original 4x6 label page(s) followed by a compact
4x6 "pack list" page that lists the items (name / SKU / qty) and the ship-to
name. This lets the supplier print every un-fulfilled label in one go and
carry a readable packing slip alongside each label while packing.
"""
import base64
import io
from dataclasses import dataclass, field

from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

LABEL_W = 4 * inch
LABEL_H = 6 * inch
MARGIN = 0.3 * inch


@dataclass
class PackItem:
    name: str
    sku: str | None
    quantity: int


@dataclass
class LabelEntry:
    order_label: str          # e.g. "Order #123" or external id
    ship_to: str | None
    tracking_number: str | None
    label_pdf: bytes | None   # decoded label PDF bytes (may be None)
    items: list[PackItem] = field(default_factory=list)


def _clip(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def _build_packlist_page(entry: LabelEntry) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_W, LABEL_H))

    y = LABEL_H - MARGIN - 0.1 * inch
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, y, _clip(f"PACK LIST — {entry.order_label}", 30))
    y -= 0.32 * inch

    c.setFont("Helvetica", 9)
    if entry.ship_to:
        c.drawString(MARGIN, y, _clip(f"Ship to: {entry.ship_to}", 50))
        y -= 0.24 * inch
    if entry.tracking_number:
        c.drawString(MARGIN, y, _clip(f"Tracking: {entry.tracking_number}", 50))
        y -= 0.24 * inch

    y -= 0.05 * inch
    c.setLineWidth(1)
    c.line(MARGIN, y, LABEL_W - MARGIN, y)
    y -= 0.3 * inch

    total_units = sum(it.quantity for it in entry.items)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN, y, f"{len(entry.items)} line(s) · {total_units} unit(s)")
    y -= 0.3 * inch

    for it in entry.items:
        if y < 0.5 * inch:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(MARGIN, y, "… more items on order")
            break
        c.setFont("Helvetica-Bold", 12)
        c.drawString(MARGIN, y, _clip(f"x{it.quantity}", 5))
        c.drawString(MARGIN + 0.55 * inch, y, _clip(it.name, 28))
        y -= 0.22 * inch
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN + 0.55 * inch, y, _clip(f"SKU: {it.sku or '—'}", 36))
        y -= 0.34 * inch

    c.showPage()
    c.save()
    return buf.getvalue()


def build_batch_label_pdf(entries: list[LabelEntry]) -> bytes:
    """Merge label pages + pack-list pages for every entry into one PDF."""
    writer = PdfWriter()
    for entry in entries:
        if entry.label_pdf:
            try:
                reader = PdfReader(io.BytesIO(entry.label_pdf))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception:
                pass  # corrupt/unreadable label — still emit the pack list
        packlist = _build_packlist_page(entry)
        writer.add_page(PdfReader(io.BytesIO(packlist)).pages[0])

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def decode_label_data(label_data: str | None) -> bytes | None:
    if not label_data:
        return None
    try:
        return base64.b64decode(label_data)
    except Exception:
        return None
