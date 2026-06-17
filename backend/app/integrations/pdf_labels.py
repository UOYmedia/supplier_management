"""Build a batch shipping-label PDF for suppliers.

For each label we overlay a compact info strip at the bottom of the carrier
label page showing the order, ship-to, and items (name / SKU / qty from the
supplier catalog). No extra pages — everything is on the carrier label itself.
"""
import base64
import io
from dataclasses import dataclass, field
from datetime import datetime

from pypdf import PdfReader, PdfWriter, Transformation
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
    supplier_name: str | None = None


def _clip(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def _smart_clip(text: str, n: int) -> str:
    """Preserve start (product identity) and end (size/variety), clip the middle."""
    text = text or ""
    if len(text) <= n:
        return text
    head = (n * 2) // 3
    tail = n - head - 1
    return text[:head] + "…" + text[len(text) - tail:]


def _draw_overlay(c: canvas.Canvas, entry: "LabelEntry") -> None:
    """Draw catalog strip in the bottom OVERLAY_H area of an already-sized canvas."""
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, LABEL_W, OVERLAY_H, fill=1, stroke=0)
    c.setStrokeColorRGB(0.4, 0.4, 0.4)
    c.setLineWidth(0.6)
    c.line(MARGIN, OVERLAY_H - 0.05 * inch, LABEL_W - MARGIN, OVERLAY_H - 0.05 * inch)

    y = OVERLAY_H - 0.22 * inch

    if entry.order_label or entry.ship_to:
        header_parts = []
        if entry.order_label:
            header_parts.append(entry.order_label)
        if entry.ship_to:
            header_parts.append(f"→ {entry.ship_to}")
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(MARGIN, y, _clip("  ".join(header_parts), 52))
        y -= 0.18 * inch

    now = datetime.now()
    date_str = now.strftime("%b").upper() + " " + str(now.day)

    for it in entry.items:
        if y < 0.06 * inch:
            c.setFont("Helvetica-Oblique", 7)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(MARGIN, y, "…more items")
            break
        name = (it.name or "").upper()
        if date_str:
            name = f"{name} – {date_str}"
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, y, str(it.quantity))
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN + 0.3 * inch, y, _smart_clip(name, 38))
        y -= 0.22 * inch


def build_label_from_png(png_bytes: bytes, entry: LabelEntry) -> bytes:
    """Single-pass: draw carrier PNG + catalog strip on one reportlab canvas."""
    from reportlab.lib.utils import ImageReader

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(LABEL_W, LABEL_H))
    usable_h = LABEL_H - OVERLAY_H
    img = ImageReader(io.BytesIO(png_bytes))
    iw, ih = img.getSize()
    scale = min(LABEL_W / iw, usable_h / ih) if iw and ih else 1.0
    w, h = iw * scale, ih * scale
    c.drawImage(
        img,
        (LABEL_W - w) / 2,
        OVERLAY_H + (usable_h - h) / 2,
        width=w,
        height=h,
        preserveAspectRatio=True,
        anchor="c",
    )
    _draw_overlay(c, entry)
    c.showPage()
    c.save()
    return buf.getvalue()


def concat_label_pdfs(pdf_list: list[bytes]) -> bytes:
    """Concatenate pre-built label PDFs (pages only, no re-overlay)."""
    writer = PdfWriter()
    for pdf in pdf_list:
        if pdf and pdf[:5] == b"%PDF-":
            try:
                reader = PdfReader(io.BytesIO(pdf))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception:
                pass
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build_batch_label_pdf(entries: list[LabelEntry]) -> bytes:
    """Fallback for PDF-based labels (manually uploaded). Uses pypdf merge."""
    writer = PdfWriter()
    for entry in entries:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(LABEL_W, LABEL_H))
        _draw_overlay(c, entry)
        c.showPage()
        c.save()
        overlay_page = PdfReader(io.BytesIO(buf.getvalue())).pages[0]

        out_page = writer.add_blank_page(width=LABEL_W, height=LABEL_H)
        if entry.label_pdf:
            try:
                carrier = PdfReader(io.BytesIO(entry.label_pdf)).pages[0]
                cw = float(carrier.mediabox.width)
                ch = float(carrier.mediabox.height)
                if cw and ch:
                    # Scale carrier to fit in the usable area above the overlay strip,
                    # then translate up so it sits above the overlay band.
                    usable_h = LABEL_H - OVERLAY_H
                    scale = min(LABEL_W / cw, usable_h / ch)
                    tx = (LABEL_W - cw * scale) / 2
                    ty = OVERLAY_H + (usable_h - ch * scale) / 2
                    out_page.merge_transformed_page(
                        carrier,
                        Transformation().scale(scale, scale).translate(tx, ty),
                    )
            except Exception:
                pass
        out_page.merge_page(overlay_page)
        out_page.mediabox.lower_left = (0, 0)
        out_page.mediabox.upper_right = (LABEL_W, LABEL_H)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def image_to_label_pdf(
    image_bytes: bytes,
    size: tuple[float, float] = (LABEL_W, LABEL_H),
    reserve_bottom: float = 0.0,
) -> bytes:
    """Wrap a raw label image (PNG/JPG) into a single-page PDF at the given size."""
    from reportlab.lib.utils import ImageReader

    buf = io.BytesIO()
    pw, ph = size
    usable_h = ph - reserve_bottom
    c = canvas.Canvas(buf, pagesize=size)
    img = ImageReader(io.BytesIO(image_bytes))
    iw, ih = img.getSize()
    scale = min(pw / iw, usable_h / ih) if iw and ih else 1.0
    w, h = iw * scale, ih * scale
    x = (pw - w) / 2
    y = reserve_bottom + (usable_h - h) / 2
    c.drawImage(img, x, y, width=w, height=h, preserveAspectRatio=True, anchor="c")
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
