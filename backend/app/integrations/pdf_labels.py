"""Shipping label PDF utilities."""
import base64
import io
from dataclasses import dataclass, field
from datetime import datetime

from pypdf import PdfReader, PdfWriter


MARGIN_PT   = 0.2 * 72   # 14.4 pt from left
TEXT_AREA_H = 0.55 * 72  # ~40 pt — conservative: fits the native blank strip


@dataclass
class PackItem:
    name: str
    sku: str | None
    quantity: int
    size: str | None = None


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


def stamp_label(carrier_pdf: bytes, entry: LabelEntry) -> bytes:
    """Stamp product info into the native blank space at the bottom of the carrier label.

    Uses pikepdf with compress_streams=False so all existing content streams
    (including barcode images) are written byte-for-byte without re-encoding.
    The text is appended as a new content stream — carrier content untouched.
    """
    import pikepdf

    # Build text lines
    date_str = ""
    if (entry.supplier_name or "").strip().upper() == "JOE":
        now = datetime.now()
        date_str = now.strftime("%b").upper() + " " + str(now.day)

    # Format: Qty + PR NAME + (size/pot if any) + (date for supplier JOE)
    # e.g. "2 PERSIMMON 1-2 FT - MAY 12"
    lines: list[str] = []
    for it in entry.items:
        parts = [str(it.quantity), (it.name or "").upper()]
        if it.size:
            parts.append(str(it.size).upper())
        line = " ".join(p for p in parts if p)
        if date_str:
            line += f" - {date_str}"
        lines.append(_smart_clip(line, 55))

    # Fallback: order_label when no catalog items
    if not lines and entry.order_label:
        lines.append(_smart_clip(entry.order_label.upper(), 55))

    if not lines:
        return carrier_pdf

    # Build raw PDF content stream with absolute Tm positioning
    line_h = 12
    y_start = MARGIN_PT + (len(lines) - 1) * line_h
    y_start = min(y_start, TEXT_AREA_H - 4)

    ops: list[bytes] = [b"q", b"BT", b"/Helvetica-Bold 8 Tf", b"0 0 0 rg"]
    y = y_start
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"1 0 0 1 {MARGIN_PT:.1f} {y:.1f} Tm".encode())
        ops.append(f"({safe}) Tj".encode())
        y -= line_h
        if y < 2:
            break
    ops += [b"ET", b"Q"]
    text_bytes = b"\n".join(ops)

    pdf = pikepdf.open(io.BytesIO(carrier_pdf))
    page = pdf.pages[0]

    # Ensure Helvetica-Bold in page Resources/Font
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

    # Append text as new content stream — carrier streams untouched
    text_stream = pikepdf.Stream(pdf, text_bytes)
    existing = page.get("/Contents")
    if existing is None:
        page["/Contents"] = text_stream
    elif isinstance(existing, pikepdf.Array):
        existing.append(pdf.make_indirect(text_stream))
    else:
        page["/Contents"] = pikepdf.Array([existing, pdf.make_indirect(text_stream)])

    out = io.BytesIO()
    # compress_streams=False → all existing streams preserved byte-for-byte
    pdf.save(out, compress_streams=False, preserve_pdfa=False)
    return out.getvalue()


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
    """Wrap a raw label image (PNG/JPG) into a single-page 4×6 PDF."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    label_w, label_h = 4 * 72, 6 * 72
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(label_w, label_h))
    img = ImageReader(io.BytesIO(image_bytes))
    iw, ih = img.getSize()
    s = min(label_w / iw, label_h / ih) if iw and ih else 1.0
    w, h = iw * s, ih * s
    c.drawImage(img, (label_w - w) / 2, (label_h - h) / 2,
                width=w, height=h, preserveAspectRatio=True, anchor="c")
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
