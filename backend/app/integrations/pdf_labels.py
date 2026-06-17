"""Shipping label PDF utilities."""
import base64
import io
from dataclasses import dataclass, field
from datetime import datetime

from pypdf import PdfReader, PdfWriter


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
    """Stamp product info text into the blank space at the bottom of the carrier label.

    Uses pikepdf to append a new content stream — all existing page streams
    (including barcode images) are preserved byte-for-byte, no re-encoding.
    """
    import pikepdf

    date_str = ""
    if (entry.supplier_name or "").strip().upper() == "JOE":
        now = datetime.now()
        date_str = now.strftime("%b").upper() + " " + str(now.day)

    # Build lines of text
    lines: list[str] = []
    for it in entry.items:
        parts = [str(it.quantity), (it.name or "").upper()]
        if it.size:
            parts.append(f"({it.size})")
        if date_str:
            parts.append(date_str)
        lines.append(_smart_clip("  ".join(parts), 55))

    if not lines:
        return carrier_pdf

    # Build raw PDF content stream operators (no external PDF needed)
    line_h = 13  # points between lines
    y_start = MARGIN_PT + (len(lines) - 1) * line_h
    y_start = min(y_start, TEXT_AREA_H - 4)

    ops: list[bytes] = [b"q", b"BT", b"/Helvetica-Bold 8 Tf", b"0 0 0 rg"]
    y = y_start
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        # Tm sets absolute text matrix: 1 0 0 1 x y Tm
        ops.append(f"1 0 0 1 {MARGIN_PT:.1f} {y:.1f} Tm".encode())
        ops.append(f"({safe}) Tj".encode())
        y -= line_h
        if y < 2:
            break
    ops += [b"ET", b"Q"]
    text_stream_bytes = b"\n".join(ops)

    pdf = pikepdf.open(io.BytesIO(carrier_pdf))
    page = pdf.pages[0]

    # Ensure Helvetica-Bold is in page Resources/Font
    if "/Resources" not in page:
        page["/Resources"] = pikepdf.Dictionary()
    res = page["/Resources"]
    if "/Font" not in res:
        res["/Font"] = pikepdf.Dictionary()
    if "/Helvetica-Bold" not in res["/Font"]:
        res["/Font"]["/Helvetica-Bold"] = pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/Type1"),
            BaseFont=pikepdf.Name("/Helvetica-Bold"),
        )

    # Append our text stream to the page's content streams
    text_stream = pikepdf.Stream(pdf, text_stream_bytes)
    existing = page.get("/Contents")
    if existing is None:
        page["/Contents"] = text_stream
    elif isinstance(existing, pikepdf.Array):
        existing.append(pdf.make_indirect(text_stream))
    else:
        # Convert single stream to array
        page["/Contents"] = pikepdf.Array([existing, pdf.make_indirect(text_stream)])

    out = io.BytesIO()
    # preserve_pdfa=False, recompress_streams=False → all existing streams untouched
    pdf.save(out, recompress_streams=False, preserve_pdfa=False)
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
