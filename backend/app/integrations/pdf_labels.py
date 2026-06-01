"""Build a batch shipping-label PDF for suppliers.

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
OVERLAY_H = 0.9 * inch  # height of info strip at the bottom of the label


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
    """Build a 4x6 overlay with catalog name + quantity in the bottom strip."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_W, LABEL_H))

    # White background strip
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, LABEL_W, OVERLAY_H, fill=1, stroke=0)

    # Separator line at top of strip
    c.setStrokeColorRGB(0.4, 0.4, 0.4)
    c.setLineWidth(0.6)
    c.line(MARGIN, OVERLAY_H - 0.05 * inch, LABEL_W - MARGIN, OVERLAY_H - 0.05 * inch)

    y = OVERLAY_H - 0.22 * inch
    row_h = 0.22 * inch

    for it in entry.items:
        if y < 0.06 * inch:
            c.setFont("Helvetica-Oblique", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(MARGIN, y, "…more items")
            break
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, y, f"x{it.quantity}")
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN + 0.3 * inch, y, _clip(it.name, 36))
        y -= row_h

    c.showPage()
    c.save()
    return buf.getvalue()


def build_batch_label_pdf(entries: list[LabelEntry]) -> bytes:
    """Overlay catalog/qty strip onto each carrier label page.

    label_pdf is always a clean 4x6 PDF (built from PNG via image_to_label_pdf),
    so no scaling or mediabox fixup is needed — just merge and overlay.
    """
    writer = PdfWriter()
    for entry in entries:
        overlay_bytes = _build_label_overlay(entry)
        overlay_page = PdfReader(io.BytesIO(overlay_bytes)).pages[0]

        out_page = writer.add_blank_page(width=LABEL_W, height=LABEL_H)

        if entry.label_pdf:
            try:
                carrier = PdfReader(io.BytesIO(entry.label_pdf)).pages[0]
                out_page.merge_page(carrier)
            except Exception:
                pass

        out_page.merge_page(overlay_page)
        out_page.mediabox.lower_left = (0, 0)
        out_page.mediabox.upper_right = (LABEL_W, LABEL_H)

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
