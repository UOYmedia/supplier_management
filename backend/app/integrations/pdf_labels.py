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


def _build_label_lines(entry: LabelEntry) -> list[str]:
    """Build the stamp text lines: Qty + PR NAME + (size/pot if any) + (date for JOE).
    e.g. "2 PERSIMMON 1-2 FT - MAY 12"
    """
    date_str = ""
    if (entry.supplier_name or "").strip().upper() == "JOE":
        now = datetime.now()
        date_str = now.strftime("%b").upper() + " " + str(now.day)

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
    return lines


def _normalize_rotation(carrier_pdf: bytes) -> bytes:
    """Bake any /Rotate into the page content so the PDF is upright with
    /Rotate 0. Returns the original bytes unchanged on any failure."""
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(io.BytesIO(carrier_pdf))
        page = reader.pages[0]
        if int(page.get("/Rotate", 0) or 0) % 360 == 0:
            return carrier_pdf
        page.transfer_rotation_to_content()
        writer = PdfWriter()
        writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        return carrier_pdf


def _find_blank_band(sm, w_px: int, h_px: int, z: float, page_h: float,
                     content_bottom: float, need: float) -> float | None:
    """Find a blank horizontal band in the label's own footer area (just above
    the bottom-most content) tall enough to hold the product lines. Returns the
    band's bottom edge (pt from top) or None. Works on an already-rendered
    grayscale pixmap (sm) so it sees actual ink — including inline images that
    fitz's element APIs don't expose."""
    # Check only the row's interior: skip the left frame border (labels are often
    # boxed, so the left edge always has ink) and the right ~18% (right-aligned
    # carrier glyphs like the UPS gift/return box).
    lo = int(w_px * 0.05)
    hi = max(lo + 1, int(w_px * 0.82))

    def row_blank(py: int) -> bool:
        base = py * w_px
        return min(sm[base + lo:base + hi]) >= 248

    p_bottom = min(h_px - 1, int(content_bottom * z))
    # Keep the search near the bottom (the billing/footer area) and not too high,
    # so the text isn't dropped into the barcode region.
    p_top = max(0, int((content_bottom - 130) * z), int(page_h * 0.45 * z))
    run = 0
    band_bottom_px = None
    for py in range(p_bottom, p_top, -1):
        if row_blank(py):
            if band_bottom_px is None:
                band_bottom_px = py
            run += 1
            if run / z >= need:
                return band_bottom_px / z
        else:
            run = 0
            band_bottom_px = None
    return None


def _crop_and_stamp_fitz(carrier_pdf: bytes, lines: list[str]) -> bytes:
    """Trim the oversized blank area some carriers (e.g. UPS) leave below the
    label, then stamp the product info into the label's existing blank footer
    band — not an added strip.

    Carrier labels are a fixed physical size (4x6), but EasyPost sometimes
    returns the label on a taller page, leaving a large white gap at the bottom.
    We detect the real content bbox, crop the page just below the bottom-most
    content (removing that gap), and place the product lines in a blank band
    inside the label's footer (e.g. between the BILLING line and the bottom
    reference codes). If no such band exists we keep a tight footer strip.

    pymupdf preserves the existing content streams / image XObjects on save
    (barcodes stay byte-for-byte — verified), so there is no quality loss.
    Raises when the page isn't a stampable portrait label, so callers fall back
    to the plain overlay path.
    """
    import fitz

    import fitz

    doc = fitz.open(stream=_normalize_rotation(carrier_pdf), filetype="pdf")
    try:
        page = doc[0]
        page_w, page_h = page.rect.width, page.rect.height
        if page_h <= page_w:
            raise ValueError("not a portrait label")

        # Render once. Carrier labels are often a single inline image, which
        # fitz's get_drawings/get_images/get_text DON'T expose — so detect the
        # real content extent from PIXELS instead.
        z = 150 / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY)
        w_px, h_px, sm = pix.width, pix.height, pix.samples

        # content_bottom = lowest row that has real ink.
        INK = 200
        content_bottom_px = None
        for py in range(h_px - 1, -1, -1):
            base = py * w_px
            if min(sm[base:base + w_px]) < INK:
                content_bottom_px = py
                break
        if content_bottom_px is None:
            raise ValueError("blank page")
        content_bottom = content_bottom_px / z
        if content_bottom < page_h * 0.45:
            raise ValueError("too little content to be a label")

        line_h = 12
        need = len(lines) * line_h + 4
        below_blank = page_h - content_bottom

        band_bottom = _find_blank_band(sm, w_px, h_px, z, page_h, content_bottom, need)

        if band_bottom is not None:
            # Drop the text into the label's existing blank footer band, and crop
            # the page tight to the real content (removes the carrier's extra
            # bottom margin → label is back to its true size).
            page.set_cropbox(fitz.Rect(0, 0, page_w, content_bottom + 4))
            y = band_bottom - 3 - (len(lines) - 1) * line_h
        elif below_blank >= need + 6:
            # No usable band but there's blank below the content — trim to a tight
            # footer and stamp just below the content.
            page.set_cropbox(fitz.Rect(0, 0, page_w, content_bottom + need + 8))
            y = content_bottom + 14
        else:
            raise ValueError("no room to stamp without overlapping content")

        for line in lines:
            page.insert_text(fitz.Point(MARGIN_PT, y), line,
                             fontname="hebo", fontsize=9)
            y += line_h

        out = io.BytesIO()
        doc.save(out, deflate=False, garbage=0)
        return out.getvalue()
    finally:
        doc.close()


def _overlay_pypdf(carrier_pdf: bytes, lines: list[str]) -> bytes:
    """Stamp the lines into the bottom-left blank strip via a reportlab overlay.

    pypdf's page merge keeps the carrier's content streams and image XObjects
    intact (barcodes stay byte-for-byte — verified), so there is no quality loss.
    Page rotation is normalised with transfer_rotation_to_content() first, so the
    text always lands upright at the *visual* bottom-left regardless of how the
    carrier stored the label (e.g. UPS labels rotated 90°).
    """
    from pypdf import PdfReader, PdfWriter, Transformation
    from reportlab.pdfgen import canvas as rl_canvas

    reader = PdfReader(io.BytesIO(carrier_pdf))
    page = reader.pages[0]
    if int(page.get("/Rotate", 0) or 0) % 360:
        page.transfer_rotation_to_content()

    box = page.mediabox
    x0, y0 = float(box.left), float(box.bottom)
    page_w, page_h = float(box.width), float(box.height)

    line_h = 12
    y = min(MARGIN_PT + (len(lines) - 1) * line_h, TEXT_AREA_H - 4)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setFont("Helvetica-Bold", 9)
    for line in lines:
        c.drawString(MARGIN_PT, y, line)
        y -= line_h
        if y < 2:
            break
    c.showPage()
    c.save()

    overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    if x0 or y0:
        page.merge_transformed_page(overlay, Transformation().translate(x0, y0))
    else:
        page.merge_page(overlay)

    writer = PdfWriter()
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _inject_pikepdf(carrier_pdf: bytes, lines: list[str]) -> bytes:
    """Fallback stamp: append a raw content stream via pikepdf (no re-encoding).
    Does not handle page rotation — used only if the pypdf overlay path fails.
    """
    import pikepdf

    line_h = 12
    y_start = min(MARGIN_PT + (len(lines) - 1) * line_h, TEXT_AREA_H - 4)

    ops: list[bytes] = [b"q", b"BT", b"/Helvetica-Bold 9 Tf", b"0 0 0 rg"]
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

    text_stream = pikepdf.Stream(pdf, text_bytes)
    existing = page.get("/Contents")
    if existing is None:
        page["/Contents"] = text_stream
    elif isinstance(existing, pikepdf.Array):
        existing.append(pdf.make_indirect(text_stream))
    else:
        page["/Contents"] = pikepdf.Array([existing, pdf.make_indirect(text_stream)])

    out = io.BytesIO()
    pdf.save(out, compress_streams=False, preserve_pdfa=False)
    return out.getvalue()


def stamp_label(carrier_pdf: bytes, entry: LabelEntry) -> bytes:
    """Stamp product info into the native blank space at the bottom of the carrier label.

    Format: Qty + PR NAME + (size/pot if any) + (date for supplier JOE),
    e.g. "2 PERSIMMON 1-2 FT - MAY 12". Returns the carrier PDF unchanged when
    there is nothing to stamp.
    """
    lines = _build_label_lines(entry)
    if not lines:
        return carrier_pdf
    # 1) Trim oversized blank area + footer stamp (handles UPS' tall pages).
    # 2) Plain rotation-safe overlay into the native bottom strip.
    # 3) Raw pikepdf content-stream injection.
    for stamp_fn in (_crop_and_stamp_fitz, _overlay_pypdf, _inject_pikepdf):
        try:
            out = stamp_fn(carrier_pdf, lines)
            if out:
                return out
        except Exception as e:
            # Log why a strategy was skipped — the crop/band path (fitz) silently
            # falling back to the plain overlay is what leaves the product name at
            # the page bottom with the oversized gap intact (e.g. pymupdf missing).
            print(f"stamp_label: {stamp_fn.__name__} failed — {type(e).__name__}: {e}", flush=True)
            continue
    return carrier_pdf


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
