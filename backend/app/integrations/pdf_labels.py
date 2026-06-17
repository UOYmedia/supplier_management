"""Shipping label PDF utilities."""
import base64
import io
from dataclasses import dataclass, field
from datetime import datetime

from pypdf import PdfReader, PdfWriter, Transformation


LABEL_W_PT = 4 * 72  # 288 pt  (1 inch = 72 pt)
LABEL_H_PT = 6 * 72  # 432 pt
MARGIN_PT  = 0.25 * 72
TEXT_AREA_H = 0.75 * 72  # height of the blank space at the bottom of the carrier label


@dataclass
class PackItem:
    name: str
    sku: str | None
    quantity: int
    size: str | None = None   # e.g. "4\"" or "6 inch pot"


@dataclass
class LabelEntry:
    order_label: str
    ship_to: str | None
    tracking_number: str | None
    label_pdf: bytes | None
    items: list[PackItem] = field(default_factory=list)
    supplier_name: str | None = None


def _smart_clip(text: str, n: int) -> str:
    text = text or ""
    if len(text) <= n:
        return text
    head = (n * 2) // 3
    tail = n - head - 1
    return text[:head] + "…" + text[len(text) - tail:]


def _stamp_items_on_pdf(carrier_pdf: bytes, entry: LabelEntry) -> bytes:
    """Stamp product info text into the existing blank space at the bottom of
    the carrier label. Carrier content stream is never modified — we only
    merge a transparent text layer on top."""
    from reportlab.pdfgen import canvas as rl_canvas

    carrier_page = PdfReader(io.BytesIO(carrier_pdf)).pages[0]
    cw = float(carrier_page.mediabox.width)
    ch = float(carrier_page.mediabox.height)

    # Build text-only overlay at the same page size (transparent background)
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(cw, ch))

    date_str = ""
    if (entry.supplier_name or "").strip().upper() == "JOE":
        now = datetime.now()
        date_str = now.strftime("%b").upper() + " " + str(now.day)

    # Draw items from the bottom up, starting MARGIN_PT from the bottom
    y = MARGIN_PT + (len(entry.items) - 1) * 14  # start high enough
    y = min(y, TEXT_AREA_H - 4)  # stay within blank area

    for it in entry.items:
        parts = [str(it.quantity), (it.name or "").upper()]
        if it.size:
            parts.append(f"({it.size})")
        if date_str:
            parts.append(date_str)
        line = "  ".join(parts)

        c.setFont("Helvetica-Bold", 8)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(MARGIN_PT, y, _smart_clip(line, 55))
        y -= 13
        if y < 2:
            break

    c.showPage()
    c.save()

    text_page = PdfReader(io.BytesIO(buf.getvalue())).pages[0]

    writer = PdfWriter()
    writer.add_page(carrier_page)
    writer.pages[0].merge_page(text_page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def stamp_label(carrier_bytes: bytes, entry: LabelEntry) -> bytes:
    """Stamp product info onto a carrier label (PDF or PNG)."""
    if carrier_bytes[:5] == b"%PDF-":
        return _stamp_items_on_pdf(carrier_bytes, entry)
    # PNG/image — wrap to PDF first, then stamp
    pdf = image_to_label_pdf(carrier_bytes)
    return _stamp_items_on_pdf(pdf, entry)


def concat_label_pdfs(pdf_list: list[bytes]) -> bytes:
    """Concatenate pre-built label PDFs into a single PDF."""
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


def image_to_label_pdf(image_bytes: bytes) -> bytes:
    """Wrap a raw label image (PNG/JPG) into a single-page PDF."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    label_w = LABEL_W_PT
    label_h = LABEL_H_PT
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(label_w, label_h))
    img = ImageReader(io.BytesIO(image_bytes))
    iw, ih = img.getSize()
    scale = min(label_w / iw, label_h / ih) if iw and ih else 1.0
    w, h = iw * scale, ih * scale
    c.drawImage(img, (label_w - w) / 2, (label_h - h) / 2, width=w, height=h,
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
