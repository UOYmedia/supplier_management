"""Shipping label PDF utilities."""
import base64
import io
from dataclasses import dataclass, field
from datetime import datetime

from pypdf import PdfReader, PdfWriter


LABEL_W_PT = 4 * 72   # 288 pt
LABEL_H_PT = 6 * 72   # 432 pt
MARGIN_PT  = 0.25 * 72
TEXT_AREA_H = 0.75 * 72  # blank space at bottom of carrier label


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


def _normalize_page_to_4x6(pdf_bytes: bytes) -> bytes:
    """If the carrier PDF is not 4×6, reframe it to 4×6 using a uniform scale
    (min of sx/sy) + centering translation, written as a PDF `cm` operator so
    the content remains vector — no rasterisation."""
    import pikepdf

    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    page = pdf.pages[0]
    mb = page.mediabox
    cw = float(mb[2]) - float(mb[0])
    ch = float(mb[3]) - float(mb[1])

    # Already 4×6 (within 1 pt tolerance) — nothing to do
    if abs(cw - LABEL_W_PT) <= 1 and abs(ch - LABEL_H_PT) <= 1:
        return pdf_bytes

    # Uniform scale to fit inside 4×6, centred
    s = min(LABEL_W_PT / cw, LABEL_H_PT / ch)
    tx = (LABEL_W_PT - cw * s) / 2
    ty = (LABEL_H_PT - ch * s) / 2

    # Wrap existing content in   q  s 0 0 s tx ty cm  ...  Q
    wrap_open  = f"q {s:.6f} 0 0 {s:.6f} {tx:.4f} {ty:.4f} cm\n".encode()
    wrap_close = b"\nQ"

    existing = page.get("/Contents")
    if existing is None:
        pass  # nothing to wrap
    elif isinstance(existing, pikepdf.Array):
        # Prepend open-wrapper stream, append close-wrapper stream
        open_stream  = pikepdf.Stream(pdf, wrap_open)
        close_stream = pikepdf.Stream(pdf, wrap_close)
        page["/Contents"] = pikepdf.Array(
            [pdf.make_indirect(open_stream)] + list(existing) + [pdf.make_indirect(close_stream)]
        )
    else:
        open_stream  = pikepdf.Stream(pdf, wrap_open)
        close_stream = pikepdf.Stream(pdf, wrap_close)
        page["/Contents"] = pikepdf.Array([
            pdf.make_indirect(open_stream),
            existing,
            pdf.make_indirect(close_stream),
        ])

    # Reframe MediaBox to exact 4×6
    page.mediabox = pikepdf.Array([0, 0, LABEL_W_PT, LABEL_H_PT])
    if "/CropBox" in page:
        page.cropbox = pikepdf.Array([0, 0, LABEL_W_PT, LABEL_H_PT])

    out = io.BytesIO()
    pdf.save(out, recompress_streams=False, preserve_pdfa=False)
    return out.getvalue()


def _stamp_items_on_pdf(carrier_pdf: bytes, entry: LabelEntry) -> bytes:
    """Stamp product info text into the blank space at the bottom of the carrier label.

    Uses pikepdf — existing streams preserved byte-for-byte (recompress_streams=False).
    Falls back to order_label when items list is empty.
    """
    import pikepdf

    date_str = ""
    if (entry.supplier_name or "").strip().upper() == "JOE":
        now = datetime.now()
        date_str = now.strftime("%b").upper() + " " + str(now.day)

    # Build text lines
    lines: list[str] = []
    for it in entry.items:
        parts = [str(it.quantity), (it.name or "").upper()]
        if it.size:
            parts.append(f"({it.size})")
        if date_str:
            parts.append(date_str)
        lines.append(_smart_clip("  ".join(parts), 55))

    # Fix 2: fallback to order_label when no catalog items resolved
    if not lines and entry.order_label:
        lines.append(_smart_clip(entry.order_label.upper(), 55))

    if not lines:
        return carrier_pdf

    # Raw PDF content stream
    line_h = 13
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
    text_stream_bytes = b"\n".join(ops)

    pdf = pikepdf.open(io.BytesIO(carrier_pdf))
    page = pdf.pages[0]

    # Ensure Helvetica-Bold in Resources/Font
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

    text_stream = pikepdf.Stream(pdf, text_stream_bytes)
    existing = page.get("/Contents")
    if existing is None:
        page["/Contents"] = text_stream
    elif isinstance(existing, pikepdf.Array):
        existing.append(pdf.make_indirect(text_stream))
    else:
        page["/Contents"] = pikepdf.Array([existing, pdf.make_indirect(text_stream)])

    out = io.BytesIO()
    pdf.save(out, recompress_streams=False, preserve_pdfa=False)
    return out.getvalue()


def stamp_label(carrier_bytes: bytes, entry: LabelEntry) -> bytes:
    """Normalize to 4×6 if needed, then stamp product info into blank bottom space."""
    if carrier_bytes[:5] == b"%PDF-":
        pdf = _normalize_page_to_4x6(carrier_bytes)
    else:
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
    """Wrap a raw label image (PNG/JPG) into a single-page 4×6 PDF."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(LABEL_W_PT, LABEL_H_PT))
    img = ImageReader(io.BytesIO(image_bytes))
    iw, ih = img.getSize()
    s = min(LABEL_W_PT / iw, LABEL_H_PT / ih) if iw and ih else 1.0
    w, h = iw * s, ih * s
    c.drawImage(img, (LABEL_W_PT - w) / 2, (LABEL_H_PT - h) / 2,
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
