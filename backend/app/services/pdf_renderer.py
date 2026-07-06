"""Fixed-layout PDF renderer for the Certificate of Deduction of Tax.

The layout is LOCKED — it reproduces certificate_format.jpeg exactly:

  * Title + "[Section 145 of the Income Tax Act 2023]" header
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
  * Footer: officer Name / Designation / Email at left; "Signature and
    seal" block at right with the uploaded seal+signature PNG and the
    auto-generated date rendered UNDER the seal/signature.

No runtime configuration of this layout is exposed anywhere.
"""
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, Image as RLImage, KeepTogether,
)
from reportlab.lib.utils import ImageReader

from ..config import get_settings


def _fitted_image(path: str, max_w_mm: float, max_h_mm: float) -> "RLImage | None":
    """Scale an uploaded image into a box without stretching it."""
    try:
        iw, ih = ImageReader(path).getSize()
    except Exception:
        return None
    if not iw or not ih:
        return None
    scale = min((max_w_mm * mm) / iw, (max_h_mm * mm) / ih)
    return RLImage(path, width=iw * scale, height=ih * scale)


_BASE = "Helvetica"
_BOLD = "Helvetica-Bold"

P_TITLE = ParagraphStyle("t", fontName=_BOLD, fontSize=13, alignment=1)
P_SUB = ParagraphStyle("s", fontName=_BASE, fontSize=9, alignment=1)
P_CELL = ParagraphStyle("c", fontName=_BASE, fontSize=8, leading=10)
P_CELL_B = ParagraphStyle("cb", fontName=_BOLD, fontSize=8, leading=10)


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d-%m-%y") if d else ""


def _fmt_issue(d: date) -> str:
    return d.strftime("%d-%b-%y")  # 21-Apr-26


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


def render_certificate_pdf(db, cert) -> str:
    """Render a Certificate ORM object (with lines loaded) to PDF; returns path."""
    from .certificate_generator import get_org_settings  # local import: no cycle at import time

    settings = get_settings()
    org = get_org_settings(db)
    out_dir = os.path.join(settings.storage_dir, "certificates")
    os.makedirs(out_dir, exist_ok=True)
    safe_no = (cert.certificate_no or f"cert-{cert.id}").replace("/", "_")
    path = os.path.join(out_dir, f"{safe_no}.pdf")

    doc = BaseDocTemplate(
        path, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title=f"Certificate of Deduction of Tax {cert.certificate_no}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])

    W = doc.width
    story = []

    # ---------- Header (repeated once at document start, as in the format) ----
    title_block = [
        Paragraph("Certificate of Deduction of Tax", P_TITLE),
        Paragraph("[Section 145 of the Income Tax Act 2023]", P_SUB),
    ]
    logo_img = (_fitted_image(org.logo_path, 24, 12)
                if org.logo_path and os.path.exists(org.logo_path) else None)
    if logo_img:
        header = Table([[logo_img, title_block, ""]],
                       colWidths=[26 * mm, W - 52 * mm, 26 * mm])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(header)
    else:
        story.extend(title_block)
    story.append(Spacer(1, 2 * mm))

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
    yes_mark = "\u2713" if has_tin else ""
    no_mark = "" if has_tin else "\u2713"

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
    story.append(s6)
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
    story.append(s7)
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
    story.append(Spacer(1, 8 * mm))

    # ---------- Footer: officer block + seal/signature + auto date -----------
    seal_cell = []
    if org.seal_signature_path and os.path.exists(org.seal_signature_path):
        img = _fitted_image(org.seal_signature_path, 45, 22)
        if img is not None:
            img.hAlign = "CENTER"
            seal_cell.append(img)
            seal_cell.append(Spacer(1, 1 * mm))
    seal_cell.append(Paragraph("<b>Signature and seal</b>",
                               ParagraphStyle("ss", parent=P_CELL_B, alignment=1)))
    seal_cell.append(Paragraph(_fmt_issue(cert.issue_date),
                               ParagraphStyle("sd", parent=P_CELL, alignment=1)))

    footer = Table(
        [[
            [Paragraph(f"<b>Name:</b> {org.officer_name or ''}", P_CELL),
             Paragraph(f"<b>Designation:</b> {org.officer_designation or ''}", P_CELL),
             Paragraph(f"<b>Email:</b> {org.officer_email or ''}", P_CELL)],
            seal_cell,
        ]],
        colWidths=[W - 60 * mm, 60 * mm],
    )
    footer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(KeepTogether([footer]))

    doc.build(story)
    return path
