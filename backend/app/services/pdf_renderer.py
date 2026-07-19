"""Fixed-layout PDF renderer for the Certificate of Deduction of Tax.

The layout is LOCKED — it reproduces certificate_format.jpeg exactly:

  * Company letterhead header (if uploaded), drawn full-bleed edge-to-edge
    across the physical page width — like branded letterhead stationery,
    not inset within the body's margins — with the title block starting
    in the clear space below it.
  * Title + "[Section 145 of the Income Tax Act 2023]" header, with a thin
    rule separating it from the "No." row
  * "No." row with certificate number left and issue date right
  * Payee block (rows 1-5): name, address, 12-digit TIN yes/no boxes,
    E-TIN + period line
  * Section 06 table: Sl | Date of Payment | Description of payment |
    Section | Amount of payment | Amount of tax deducted | Remarks
    (one row per actual payment line, no blank filler rows) + Total row
  * Section 07 table: Sl | Challan Number | Challan date | Bank Name |
    Total amount in the challan | Amount relating to this certificate |
    Remarks + Total row (total of "amount relating" only)
  * Amount In word + certification line
  * Footer block, pinned to a fixed position at the bottom of the page (a
    dedicated ReportLab Frame, not just appended after the content — so it
    never "floats" up on short certificates or collides with content on
    long ones): one "Seal and Signature" unit, flush against the right
    margin (mirroring the left margin's distance from the page edge),
    stacked top to bottom — signature image, the "Seal and Signature"
    label, the issue date (DD Month YYYY), then the seal image directly
    below the date, all centered on each other within the block's own
    column. The signature shown is the first enabled Signature for this
    cert's company (alphabetical by name); a labeled placeholder box
    stands in for either image if it isn't configured yet.
  * Company letterhead footer (if uploaded), drawn full-bleed edge-to-edge
    across the bottom of the physical page, below the signature/seal row's
    margin-bound space.
  * Company letterhead header/footer are always resolved from the
    certificate's own company, never the currently-active UI company.

No company/certificate logo is rendered anywhere in this template — that
feature has been removed. No runtime configuration of this layout is
exposed anywhere.

Alongside the PDF, a share-ready JPEG (Certificate.image_data) is rasterized
from that same PDF on every (re)generation — not a second independent
render — so on-screen view, print, WhatsApp, and email image sharing all
trace back to one source layout and stay pixel-identical to each other.

Every image (uploaded letterhead/seal/signature, generated PDF, generated
share image) is handled as in-memory bytes and stored in the database, never
written to local disk — this backend runs on stateless/serverless hosting
(e.g. Vercel), where each request can get a fresh, empty filesystem.
"""
import io
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, Frame, FrameBreak, HRFlowable, KeepTogether, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, Image as RLImage,
)
from reportlab.lib.utils import ImageReader

from ..models.entities import Signature

# Fixed height reserved for the bottom-pinned footer frame — just the Seal
# and Signature block now, sized to reclaim page height for Section 06/07
# rows (fewer line items overflow onto a second page before it's needed).
_FOOTER_H = 52 * mm


def _fitted_image(data: bytes | None, max_w_mm: float, max_h_mm: float) -> "RLImage | None":
    """Scale an uploaded image into a box without stretching it."""
    if not data:
        return None
    try:
        iw, ih = ImageReader(io.BytesIO(data)).getSize()
    except Exception:
        return None
    if not iw or not ih:
        return None
    scale = min((max_w_mm * mm) / iw, (max_h_mm * mm) / ih)
    return RLImage(io.BytesIO(data), width=iw * scale, height=ih * scale)


_BASE = "Helvetica"
_BOLD = "Helvetica-Bold"

P_TITLE = ParagraphStyle("t", fontName=_BOLD, fontSize=15, alignment=1,
                         textColor=colors.Color(0.08, 0.08, 0.08), spaceAfter=2)
P_SUB = ParagraphStyle("s", fontName=_BASE, fontSize=9, alignment=1,
                       textColor=colors.Color(0.4, 0.4, 0.4))
P_CELL = ParagraphStyle("c", fontName=_BASE, fontSize=8, leading=10)
P_CELL_B = ParagraphStyle("cb", fontName=_BOLD, fontSize=8, leading=10)
P_CENTER = ParagraphStyle("ctr", parent=P_CELL, alignment=1)
P_CENTER_B = ParagraphStyle("ctrb", parent=P_CELL_B, alignment=1)
P_PLACEHOLDER = ParagraphStyle("ph", parent=P_CENTER, textColor=colors.Color(0.6, 0.6, 0.6))

# WhatsApp/email share image: long enough edge to avoid WhatsApp's own
# aggressive re-compression, small enough to stay well under typical
# attachment limits.
_SHARE_IMAGE_LONG_EDGE_PX = 1800
_SHARE_IMAGE_JPEG_QUALITY = 88


def export_certificate_image(pdf_bytes: bytes) -> bytes:
    """Rasterize a certificate PDF into JPEG bytes — from the PDF itself,
    not a second independent render, so it is pixel-for-pixel identical to
    the PDF (same fonts, same layout, same right-aligned Seal and Signature
    block). Also used to self-heal certificates that have no image yet.

    An unusually large certificate (many Section 06/07 rows) can overflow
    onto a second PDF page — the bottom-pinned footer frame then correctly
    follows onto whichever page the content ends on, per normal pagination.
    Every page is rasterized and stacked vertically here so the Seal and
    Signature block is never silently dropped just because it landed on
    page 2 rather than page 1."""
    import fitz  # local import: only this one call needs it
    from PIL import Image

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        long_edge_pt = max(doc[0].rect.width, doc[0].rect.height)
        zoom = _SHARE_IMAGE_LONG_EDGE_PX / long_edge_pt
        matrix = fitz.Matrix(zoom, zoom)
        page_images = [
            Image.open(io.BytesIO(page.get_pixmap(matrix=matrix).tobytes("png"))).convert("RGB")
            for page in doc
        ]
    finally:
        doc.close()

    if len(page_images) == 1:
        combined = page_images[0]
    else:
        width = max(img.width for img in page_images)
        combined = Image.new("RGB", (width, sum(img.height for img in page_images)), "white")
        y = 0
        for img in page_images:
            combined.paste(img, (0, y))
            y += img.height

    out = io.BytesIO()
    combined.save(out, "JPEG", quality=_SHARE_IMAGE_JPEG_QUALITY)
    return out.getvalue()


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d-%m-%y") if d else ""


def _fmt_issue(d: date) -> str:
    return d.strftime("%d-%b-%y")  # 21-Apr-26


def _fmt_date_long(d: date) -> str:
    return d.strftime("%d %B %Y")  # 14 March 2025 — bottom-section Seal/Signature date only


def _fmt_amt(v: float | None, decimals_if_needed=True) -> str:
    if v is None:
        return ""
    if abs(v - round(v)) < 0.005:
        return f"{round(v):,}"
    return f"{v:,.2f}"


def _period_label(d_from: date | None, d_to: date | None) -> str:
    def lab(d):
        return d.strftime("%-d %b'%y") if os.name != "nt" else d.strftime("%#d %b'%y")
    if d_from and d_to:
        return f"From {lab(d_from)} to {lab(d_to)}"
    return ""


def _placeholder_box(label: str, w_mm: float, h_mm: float) -> Table:
    """A clearly-marked empty box standing in for a not-yet-uploaded
    signature/seal image, so the layout reads correctly before either is
    configured in Settings."""
    box = Table([[Paragraph(label, P_PLACEHOLDER)]],
               colWidths=[w_mm * mm], rowHeights=[h_mm * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, colors.Color(0.7, 0.7, 0.7)),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return box


_MAX_BLEED_H = 55 * mm  # letterhead banners never eat more than this much page height


def _bleed_box(data: bytes | None, page_w: float) -> tuple[float, float, float] | None:
    """Full-bleed placement for a letterhead banner: spans the entire
    physical page width edge-to-edge (like real branded stationery — no
    content margin on the sides), at its natural aspect ratio, capped to
    _MAX_BLEED_H. Returns (x, width, height) in points, or None if there's
    no image or it can't be read."""
    if not data:
        return None
    try:
        iw, ih = ImageReader(io.BytesIO(data)).getSize()
    except Exception:
        return None
    if not iw or not ih:
        return None
    height = page_w * (ih / iw)
    if height <= _MAX_BLEED_H:
        return 0.0, page_w, height
    # Unusually tall/narrow upload: fall back to fitting the height cap,
    # centered, rather than letting it swallow the page.
    width = _MAX_BLEED_H * (iw / ih)
    return (page_w - width) / 2, width, _MAX_BLEED_H


def render_certificate_pdf(db, cert) -> None:
    """Render a Certificate ORM object (with lines loaded) to PDF bytes and
    a rasterized share image, storing both directly on the cert (does not
    commit — callers are already responsible for that)."""
    from .certificate_generator import get_org_settings  # local import: no cycle at import time

    org = get_org_settings(db)
    company = cert.company

    page_w, page_h = A4

    header_data = company.letterhead_header_data if company else None
    footer_data = company.letterhead_footer_data if company else None
    header_box = _bleed_box(header_data, page_w)
    footer_box = _bleed_box(footer_data, page_w)
    # A small gap between the bleed banner and the margin-bound body content,
    # so text never sits flush against the artwork's edge.
    header_reserve = (header_box[2] + 3 * mm) if header_box else 0
    footer_reserve = (footer_box[2] + 3 * mm) if footer_box else 0

    def _draw_letterhead(canvas, _doc):
        canvas.saveState()
        if header_box:
            x, w, h = header_box
            canvas.drawImage(ImageReader(io.BytesIO(header_data)), x, page_h - h, width=w, height=h,
                             preserveAspectRatio=True, anchor="n", mask="auto")
        if footer_box:
            x, w, h = footer_box
            canvas.drawImage(ImageReader(io.BytesIO(footer_data)), x, 0, width=w, height=h,
                             preserveAspectRatio=True, anchor="s", mask="auto")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title=f"Certificate of Deduction of Tax {cert.certificate_no}",
    )
    content_frame = Frame(
        doc.leftMargin, doc.bottomMargin + _FOOTER_H + footer_reserve,
        doc.width, doc.height - _FOOTER_H - header_reserve - footer_reserve,
        id="content",
    )
    footer_frame = Frame(
        doc.leftMargin, doc.bottomMargin + footer_reserve, doc.width, _FOOTER_H,
        id="footer",
    )
    doc.addPageTemplates([PageTemplate(id="page", frames=[content_frame, footer_frame],
                                       onPage=_draw_letterhead)])

    W = doc.width
    story = []

    # ---------- Title (no logo — removed) -------------------------------------
    story.append(Paragraph("Certificate of Deduction of Tax", P_TITLE))
    story.append(Paragraph("[Section 145 of the Income Tax Act 2023]", P_SUB))
    story.append(Spacer(1, 2.5 * mm))
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.Color(0.75, 0.75, 0.75),
                            spaceBefore=0, spaceAfter=3 * mm))

    no_tbl = Table(
        [["No.", cert.certificate_no or "", _fmt_issue(cert.issue_date)]],
        colWidths=[10 * mm, W - 10 * mm - 30 * mm, 30 * mm],
    )
    no_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), _BOLD, 9),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.black),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(no_tbl)
    story.append(Spacer(1, 2 * mm))

    supplier = cert.supplier
    has_tin = cert.has_12_digit_tin
    yes_mark = "✓" if has_tin else ""
    no_mark = "" if has_tin else "✓"

    payee_rows = [
        ["1", Paragraph("<b>Name of Payee:</b>", P_CELL),
         Paragraph(supplier.name or "", P_CELL), "", "", ""],
        ["2", Paragraph("<b>Address of Payee:</b>", P_CELL),
         Paragraph(supplier.address or "", P_CELL), "", "", ""],
        ["3", Paragraph("Does the person have a Twelve-digit TIN?", P_CELL),
         "", f"Yes  [{yes_mark or '  '}]", "", f"No  [{no_mark or '  '}]"],
        ["4", Paragraph("Twelve-digit TIN (if answer of 03 is Yes)", P_CELL),
         "E-TIN", cert.tin or "", "", ""],
        ["5", Paragraph("Period for which payment is made From (date) to (date)", P_CELL),
         "", Paragraph(_period_label(cert.period_from, cert.period_to), P_CELL), "", ""],
    ]
    payee_tbl = Table(
        payee_rows,
        colWidths=[8 * mm, 62 * mm, 18 * mm, 46 * mm, 10 * mm,
                   W - (8 + 62 + 18 + 46 + 10) * mm],
    )
    payee_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), _BASE, 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("SPAN", (2, 0), (5, 0)), ("SPAN", (2, 1), (5, 1)),
        ("SPAN", (3, 3), (5, 3)),
        ("SPAN", (3, 4), (5, 4)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(payee_tbl)
    story.append(Spacer(1, 3 * mm))

    # ---------- Section 06 ---------------------------------------------------
    story.append(Paragraph(
        "<b>06. Particulars of the making of payment and the deduction of tax "
        "(add lines if necessary)</b>", P_CELL))
    story.append(Spacer(1, 1 * mm))

    s6_header = ["Sl", "Date of Payment", "Description of\npayment", "Section",
                 "Amount of\npayment", "Amount of tax\ndeducted", "Remarks"]
    s6_rows = [s6_header]
    lines = list(cert.lines)
    n_rows = max(1, len(lines))
    for i in range(n_rows):
        if i < len(lines):
            ln = lines[i]
            s6_rows.append([
                str(ln.sl), _fmt_date(ln.date_of_payment),
                Paragraph(ln.description or "", P_CELL), ln.section or "",
                _fmt_amt(ln.amount_of_payment), _fmt_amt(ln.amount_of_tax_deducted),
                Paragraph(cert.remarks or "", P_CELL) if i == 0 else "",
            ])
        else:
            s6_rows.append([
                str(i + 1), "", "", "", "", "",
                Paragraph(cert.remarks or "", P_CELL) if i == 0 else "",
            ])
    s6_rows.append(["", "Total", "", "",
                    _fmt_amt(cert.total_payment), _fmt_amt(cert.total_tax_deducted), ""])

    s6_widths = [9 * mm, 27 * mm, 38 * mm, 18 * mm, 28 * mm, 28 * mm,
                 W - (9 + 27 + 38 + 18 + 28 + 28) * mm]
    s6 = Table(s6_rows, colWidths=s6_widths, repeatRows=1)
    s6.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), _BOLD, 8),
        ("FONT", (0, 1), (-1, -1), _BASE, 8),
        ("FONT", (1, -1), (1, -1), _BOLD, 8),
        ("FONT", (4, -1), (5, -1), _BOLD, 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -2), "CENTER"),
        ("ALIGN", (3, 1), (3, -2), "CENTER"),
        ("ALIGN", (4, 1), (5, -1), "RIGHT"),
        ("ALIGN", (1, -1), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (6, 1), (6, n_rows)),
        ("VALIGN", (6, 1), (6, n_rows), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    # KeepTogether: the Remarks column is SPANned down the whole table, and
    # ReportLab's row-splitter can't cleanly split a table mid-span (it
    # crashes trying to compute row heights across the break). Keeping the
    # table atomic pushes it whole onto the next page instead, which also
    # means the table itself is never cut mid-row across a page boundary.
    story.append(KeepTogether([s6]))
    story.append(Spacer(1, 5 * mm))

    # ---------- Section 07 ---------------------------------------------------
    story.append(Paragraph(
        "<b>07. Payment of deducted tax to the credit of the Government "
        "(add lines if necessary)</b>", P_CELL))
    story.append(Spacer(1, 1 * mm))

    s7_header = ["Sl", "Challan Number", "Challan date", "Bank Name",
                 "Total amount in\nthe challan", "Amount relating\nto this certificate",
                 "Remarks"]
    s7_rows = [s7_header]
    chlines = list(cert.challan_lines)
    n7 = max(1, len(chlines))
    for i in range(n7):
        if i < len(chlines):
            cl = chlines[i]
            s7_rows.append([
                str(cl.sl), cl.challan_number or "", _fmt_date(cl.challan_date),
                Paragraph(cl.bank_name or "", P_CELL),
                _fmt_amt(cl.total_challan_amount), _fmt_amt(cl.amount_related),
                Paragraph(cert.remarks or "", P_CELL) if i == 0 else "",
            ])
        else:
            s7_rows.append([
                str(i + 1), "", "", "", "", "",
                Paragraph(cert.remarks or "", P_CELL) if i == 0 else "",
            ])
    s7_rows.append(["", "Total", "", "", "", _fmt_amt(cert.total_tax_deducted), ""])

    s7_widths = [9 * mm, 36 * mm, 22 * mm, 30 * mm, 28 * mm, 30 * mm,
                 W - (9 + 36 + 22 + 30 + 28 + 30) * mm]
    s7 = Table(s7_rows, colWidths=s7_widths, repeatRows=1)
    s7.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), _BOLD, 8),
        ("FONT", (0, 1), (-1, -1), _BASE, 8),
        ("FONT", (1, -1), (1, -1), _BOLD, 8),
        ("FONT", (5, -1), (5, -1), _BOLD, 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -2), "CENTER"),
        ("ALIGN", (4, 1), (5, -1), "RIGHT"),
        ("ALIGN", (1, -1), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (6, 1), (6, n7)),
        ("VALIGN", (6, 1), (6, n7), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(KeepTogether([s7]))  # same SPAN-vs-split issue as Section 06
    story.append(Spacer(1, 4 * mm))

    # ---------- Amount in words + certification ------------------------------
    aiw_rows = [
        [Paragraph("<b>Amount In word:</b>", P_CELL),
         Paragraph(cert.amount_in_words or "", P_CELL)],
        ["", Paragraph("Certified that the information given above is correct "
                       "and complete.", P_CELL)],
    ]
    aiw = Table(aiw_rows, colWidths=[35 * mm, W - 35 * mm])
    aiw.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(aiw)

    # ---------- Footer, pinned to a fixed frame at the bottom of the page ----
    # One combined "Seal and Signature" unit, centered as a single block:
    # signature image, then the label, then the issue date (DD Month YYYY),
    # then the seal image directly below the date. If either image isn't
    # configured yet, a labeled placeholder box stands in for it.
    story.append(FrameBreak())

    signature = (
        db.query(Signature)
        .filter(Signature.company_id == cert.company_id, Signature.enabled.is_(True))
        .order_by(Signature.name)
        .first()
    )

    # Seal resolution: this cert's own company, else the legacy OrgSettings
    # field, else (only if nothing at all is configured) the old combined
    # seal+signature image kept for backwards compatibility.
    seal_data = None
    if company and company.seal_data:
        seal_data = company.seal_data
    elif org.seal_data:
        seal_data = org.seal_data
    elif not signature and org.seal_signature_data:
        seal_data = org.seal_signature_data

    block = []
    sig_img = _fitted_image(signature.image_data, 40, 16) if signature else None
    if sig_img is not None:
        sig_img.hAlign = "CENTER"
        block.append(sig_img)
    else:
        block.append(_placeholder_box("Signature", 40, 16))
    block.append(Spacer(1, 1.5 * mm))
    block.append(Paragraph("<b>Seal and Signature</b>", P_CENTER_B))
    block.append(Paragraph(_fmt_date_long(cert.issue_date), P_CENTER))
    block.append(Spacer(1, 1.5 * mm))
    seal_img = _fitted_image(seal_data, 30, 16)
    if seal_img is not None:
        seal_img.hAlign = "CENTER"
        block.append(seal_img)
    else:
        block.append(_placeholder_box("Seal", 30, 16))

    # The block sits flush against the right margin (the same distance from
    # the page's right edge as the body content's left edge is from the
    # left, since the footer frame already respects both side margins) —
    # a narrow right-hand column holds it, elements centered on each other
    # within that column so the stack reads as one clean unit.
    BLOCK_W = 55 * mm
    footer = Table([["", block]], colWidths=[W - BLOCK_W, BLOCK_W])
    footer.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(footer)

    doc.build(story)

    cert.pdf_data = buf.getvalue()
    # Share-ready image (WhatsApp/email/on-screen preview), rasterized from
    # this same PDF so it's guaranteed to match it exactly.
    cert.image_data = export_certificate_image(cert.pdf_data)
