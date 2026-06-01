"""
Build a batch shipping-label PDF for suppliers.

For each label we overlay a compact info strip at the bottom of the carrier
label page showing the order, ship-to, and items (name / SKU / qty from the
supplier catalog). No extra pages — everything is on the carrier label itself.
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
OVERLAY_H = 1.65 * inch  # height of info strip at the bottom of the label


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


def _build_label_overlay(entry: LabelEntry) -> bytes:
    """Build a 4x6 overlay with item info in the bottom strip of the label."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_W, LABEL_H))

    # White background strip to cover any carrier content underneath
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, LABEL_W, OVERLAY_H, fill=1, stroke=0)

    # Separator line at top of strip
    c.setStrokeColorRGB(0.2, 0.2, 0.2)
    c.setLineWidth(0.8)
    c.line(MARGIN, OVERLAY_H - 0.06 * inch, LABEL_W - MARGIN, OVERLAY_H - 0.06 * inch)

    y = OVERLAY_H - 0.24 * inch

    # Header: order label + ship-to on one compact line
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 7)
    header = _clip(entry.order_label or "", 18)
    if entry.ship_to:
        header += f"  ▸  {_clip(entry.ship_to, 22)}"
    c.drawString(MARGIN, y, header)
    y -= 0.21 * inch

    # Items (using supplier catalog name)
    for it in entry.items:
        if y < 0.07 * inch:
            c.setFont("Helvetica-Oblique", 6)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(MARGIN, y, "…more items")
            break
        # Quantity
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, y, f"x{it.quantity}")
        # Catalog name
        c.setFont("Helvetica", 8.5)
        c.drawString(MARGIN + 0.32 * inch, y, _clip(it.name, 32))
        y -= 0.19 * inch
        # SKU
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.45, 0.45, 0.45)
        c.drawString(MARGIN + 0.32 * inch, y, _clip(f"SKU: {it.sku or '—'}", 40))
        c.setFillColorRGB(0, 0, 0)
        y -= 0.22 * inch

    c.showPage()
    c.save()
    return buf.getvalue()


def build_batch_label_pdf(entries: list[LabelEntry]) -> bytes:
    """Overlay item info onto each carrier label page — no extra pages added."""
    writer = PdfWriter()
    for entry in entries:
        overlay_bytes = _build_label_overlay(entry)
        overlay_page = PdfReader(io.BytesIO(overlay_bytes)).pages[0]

        if entry.label_pdf:
            try:
                reader = PdfReader(io.BytesIO(entry.label_pdf))
                for i, page in enumerate(reader.pages):
                    if i == 0:
                        # Overlay info strip onto the first (carrier) page
                        page.merge_page(overlay_page)
                    writer.add_page(page)
            except Exception:
                # Corrupt/unreadable label — emit the overlay on a blank page
                writer.add_page(overlay_page)
        else:
            # No carrier PDF yet — emit overlay on a blank page
            writer.add_page(overlay_page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def image_to_label_pdf(image_bytes: bytes, size: tuple[float, float] = (LABEL_W, LABEL_H)) -> bytes:
    """Wrap a raw label image (PNG/JPG) into a single-page PDF at the given size."""
    from reportlab.lib.utils import ImageReader

    buf = io.BytesIO()
    pw, ph = size
    c = canvas.Canvas(buf, pagesize=size)
    img = ImageReader(io.BytesIO(image_bytes))
    iw, ih = img.getSize()
    scale = min(pw / iw, ph / ih) if iw and ih else 1.0
    w, h = iw * scale, ih * scale
    c.drawImage(img, (pw - w) / 2, (ph - h) / 2, width=w, height=h,
                preserveAspectRatio=True, anchor="c")
    c.showPage()
    c.save()
    return buf.getvalue()


def decode_label_data(label_data: str | None) -> bytes | None:
    if not label_data:
        return None
    try:
        return base64.b64decode(label_data)
    except Exception:
        return None
