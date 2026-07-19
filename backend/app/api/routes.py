"""All API routers for the module, mounted under /api."""
import io
import os
import shutil
import tempfile
from zipfile import BadZipFile
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import and_, func, or_, true
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    Certificate,
    CertificateChallanLine,
    CertificateLine,
    CertStatus,
    Company,
    ContactKind,
    DispatchChannel,
    DispatchJob,
    ImportBatch,
    ImportRowError,
    NumberSequence,
    NumberingConfig,
    OrgSettings,
    OverrideLog,
    RateAnomaly,
    Signature,
    Supplier,
    SupplierContact,
    TaxRate,
    Transaction,
)
from ..schemas import (
    AnomalyOut,
    BulkAnomalyOut,
    BulkDispatchRequest,
    BulkDispatchResultOut,
    BulkFilterRequest,
    BulkGenerateRequest,
    CertificateDetailOut,
    CertificateOut,
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    ContactCreate,
    DispatchRequest,
    GenerateRequest,
    ImportBatchOut,
    IssueDateUpdate,
    NumberingIn,
    OrgSettingsIn,
    RateUpdateIn,
    RemarksUpdate,
    SignatureOut,
    SignatureUpdate,
    SupplierCreate,
    TinStatusUpdate,
    DatabaseResetRequest,
    SupplierOut,
    SupplierUpdate,
)
from ..services import rate_hook
from ..services.aggregation import list_groupings
from ..services.certificate_generator import (
    GenerationError,
    generate_certificate,
    get_company,
    get_org_settings,
    regenerate_pdf,
)
from ..services.dispatch import DispatchBlocked, enqueue_dispatch, process_queue
from ..services.dispatch.email_sender import send_test_email, verify_job_sig
from ..services.dispatch.whatsapp_sender import verify_certificate_sig
from ..services.excel_export import export_certificates_to_excel
from ..services.pdf_renderer import render_certificate_pdf
from ..services.excel_import import (
    import_depot_workbook,
    load_depot_sheet,
)
from ..services.numbering import get_numbering_config
from ..services.validation import check_certificate

router = APIRouter(prefix="/api")


def _certificates_matching(db: Session, f: BulkFilterRequest):
    """Shared filter builder for the bulk anomaly check and bulk send
    endpoints — same combinable filters as GET /certificates."""
    q = db.query(Certificate).join(Supplier).filter(Certificate.company_id == f.company_id)
    if f.tin:
        q = q.filter(Certificate.tin.like(f"%{f.tin}%"))
    if f.bin:
        q = q.filter(Supplier.bin.like(f"%{f.bin}%"))
    if f.supplier_name:
        q = q.filter(Supplier.name.ilike(f"%{f.supplier_name}%"))
    if f.date_from or f.date_to:
        issue_in_range = and_(
            Certificate.issue_date >= f.date_from if f.date_from else true(),
            Certificate.issue_date <= f.date_to if f.date_to else true(),
        )
        period_overlaps = and_(
            or_(Certificate.period_to.is_(None), Certificate.period_to >= f.date_from) if f.date_from else true(),
            or_(Certificate.period_from.is_(None), Certificate.period_from <= f.date_to) if f.date_to else true(),
        )
        q = q.filter(or_(issue_in_range, period_overlaps))
    if f.status:
        q = q.filter(Certificate.status == f.status)
    else:
        q = q.filter(Certificate.status != CertStatus.VOID)
    return q


def _save_upload(upload: UploadFile) -> str:
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(upload.filename or "")[1])
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return path


def _sniff_image_mime(data: bytes) -> str:
    """Uploaded images are stored as raw bytes in the database (no local
    disk, no filename/extension to rely on) — sniff the real format from
    its magic bytes so the Content-Type served back is always correct."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "application/octet-stream"


# ---------------------------------------------------------------- Import ----
@router.post("/import/depot", response_model=ImportBatchOut)
def upload_depot(company_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Upload an .xlsx workbook")
    path = _save_upload(file)
    try:
        batch = import_depot_workbook(db, path, file.filename or "upload.xlsx", company_id)
        df = load_depot_sheet(path)
        columns = [c for c in df.columns if c != "__excel_row"]
        rows = []
        for _, r in df.iterrows():
            row = {"__excel_row": int(r["__excel_row"])}
            for c in columns:
                v = r.get(c)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    row[c] = ""
                elif isinstance(v, (pd.Timestamp, datetime, date)):
                    row[c] = v.strftime("%d/%m/%Y")
                else:
                    row[c] = str(v)
            rows.append(row)
        out = ImportBatchOut.model_validate(batch)
        out.rows = rows
        out.columns = columns
        return out
    except (BadZipFile, ValueError) as e:
        db.rollback()
        raise HTTPException(422, f"Could not read workbook: {e}")
    except Exception as e:  # noqa: BLE001 - keep upload failures user-readable
        db.rollback()
        raise HTTPException(422, f"Could not import workbook: {e}")
    finally:
        if os.path.exists(path):
            os.unlink(path)


@router.get("/import/batches", response_model=list[ImportBatchOut])
def list_batches(company_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(ImportBatch)
    if company_id is not None:
        q = q.filter(ImportBatch.company_id == company_id)
    return q.order_by(ImportBatch.created_at.desc()).limit(50).all()


# ---------------------------------------------------------- Certificates ----
@router.get("/certificates/pending")
def pending_groupings(
    company_id: int | None = None,
    tin: str | None = None,
    bin: str | None = None,
    supplier_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """(TIN, period) groupings with no certificate yet, scoped to a company
    (or across all companies, for the Dashboard's global overview). Same
    filters as GET /certificates so Pending and Generated search identically
    instead of diverging (item 8)."""
    issued_q = db.query(Certificate).filter(Certificate.status != CertStatus.VOID)
    if company_id is not None:
        issued_q = issued_q.filter(Certificate.company_id == company_id)
    issued = {(c.tin, c.period) for c in issued_q}
    groupings = list_groupings(db, company_id, tin=tin, bin=bin,
                               supplier_name=supplier_name,
                               date_from=date_from, date_to=date_to)
    return [g for g in groupings if (g["tin"], g["period"]) not in issued]


@router.get("/certificates")
def search_certificates(
    company_id: int,
    tin: str | None = None,
    bin: str | None = None,
    supplier_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Combinable search: TIN, BIN, Supplier Name, Date range. Paginated."""
    q = db.query(Certificate).join(Supplier).filter(Certificate.company_id == company_id)
    if tin:
        q = q.filter(Certificate.tin.like(f"%{tin}%"))
    if bin:
        q = q.filter(Supplier.bin.like(f"%{bin}%"))
    if supplier_name:
        q = q.filter(Supplier.name.ilike(f"%{supplier_name}%"))
    if date_from or date_to:
        # A certificate matches if either its issue date falls in the range,
        # or its payment period overlaps the range (mirrors the Pending table).
        issue_in_range = and_(
            Certificate.issue_date >= date_from if date_from else true(),
            Certificate.issue_date <= date_to if date_to else true(),
        )
        period_overlaps = and_(
            or_(Certificate.period_to.is_(None), Certificate.period_to >= date_from) if date_from else true(),
            or_(Certificate.period_from.is_(None), Certificate.period_from <= date_to) if date_to else true(),
        )
        q = q.filter(or_(issue_in_range, period_overlaps))
    if status:
        q = q.filter(Certificate.status == status)
    total = q.count()
    items = (
        q.order_by(Certificate.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [CertificateOut.model_validate(c).model_dump() for c in items],
    }


@router.post("/certificates/generate", response_model=CertificateDetailOut)
def generate(req: GenerateRequest, db: Session = Depends(get_db)):
    try:
        return generate_certificate(db, req.company_id, req.tin, req.period)
    except GenerationError as e:
        raise HTTPException(409, str(e))


@router.post("/certificates/generate/bulk")
def generate_bulk(req: BulkGenerateRequest, db: Session = Depends(get_db)):
    results = []
    for item in req.items:
        try:
            cert = generate_certificate(db, item.company_id, item.tin, item.period)
            results.append({"tin": item.tin, "period": item.period,
                            "ok": True, "certificate_no": cert.certificate_no})
        except GenerationError as e:
            db.rollback()
            results.append({"tin": item.tin, "period": item.period,
                            "ok": False, "error": str(e)})
    return results


@router.get("/certificates/export")
def export_certificates(
    company_id: int,
    tin: str | None = None,
    bin: str | None = None,
    supplier_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    certificate_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Item 11: Excel export (Depot-SCB schema, no VDS, anomaly-highlighted)
    for the filtered set, or a single certificate via certificate_id.

    Registered before /certificates/{cert_id} — path-param routes are
    greedy in FastAPI's registration-order matching, so this literal path
    must come first or "export" gets swallowed as a cert_id and 422s.
    """
    if certificate_id is not None:
        cert = db.get(Certificate, certificate_id)
        certs = [cert] if cert else []
    else:
        filters = BulkFilterRequest(company_id=company_id, tin=tin, bin=bin,
                                    supplier_name=supplier_name, date_from=date_from,
                                    date_to=date_to, status=status)
        certs = _certificates_matching(db, filters).all()
    if not certs:
        raise HTTPException(404, "No certificates match")
    wb = export_certificates_to_excel(db, certs)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = (f"certificate-{certs[0].certificate_no or certs[0].id}.xlsx"
                if certificate_id is not None else "certificates-export.xlsx")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/certificates/{cert_id}", response_model=CertificateDetailOut)
def get_certificate(cert_id: int, db: Session = Depends(get_db)):
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    return cert


@router.patch("/certificates/{cert_id}/remarks", response_model=CertificateDetailOut)
def update_remarks(cert_id: int, body: RemarksUpdate, db: Session = Depends(get_db)):
    """Remarks and has_12_digit_tin are the only editable fields."""
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    cert.remarks = body.remarks
    regenerate_pdf(db, cert)  # re-render so the PDF reflects the new remarks
    return cert


@router.patch("/certificates/{cert_id}/tin-status", response_model=CertificateDetailOut)
def update_tin_status(cert_id: int, body: TinStatusUpdate, db: Session = Depends(get_db)):
    """Row 3 Yes/No override for the Twelve-digit TIN question."""
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    cert.has_12_digit_tin = body.has_12_digit_tin
    regenerate_pdf(db, cert)  # re-render so the PDF reflects the new answer
    return cert


@router.patch("/certificates/{cert_id}/issue-date", response_model=CertificateDetailOut)
def update_issue_date(cert_id: int, body: IssueDateUpdate, db: Session = Depends(get_db)):
    """Item 4: preview lets the user pick Automatic (today, re-applied on
    every save) or Manual (a fixed date the officer enters)."""
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if body.mode == "manual":
        if not body.issue_date:
            raise HTTPException(422, "issue_date is required when mode is 'manual'")
        cert.issue_date = body.issue_date
    else:
        cert.issue_date = date.today()
    cert.issue_date_mode = body.mode
    regenerate_pdf(db, cert)  # re-render so the PDF reflects the new date
    return cert


@router.get("/certificates/{cert_id}/anomalies", response_model=list[AnomalyOut])
def certificate_anomalies(cert_id: int, db: Session = Depends(get_db)):
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    org = get_org_settings(db)
    return [AnomalyOut(code=a.code, message=a.message)
            for a in check_certificate(db, cert, org)]


@router.post("/certificates/anomalies/bulk", response_model=list[BulkAnomalyOut])
def bulk_anomaly_check(body: BulkFilterRequest, db: Session = Depends(get_db)):
    """Item 5: one-click bulk anomaly check across every certificate matching
    the given filters. Only certificates with at least one anomaly appear."""
    org = get_org_settings(db)
    certs = _certificates_matching(db, body).all()
    results = []
    for cert in certs:
        anomalies = check_certificate(db, cert, org)
        if anomalies:
            results.append(BulkAnomalyOut(
                certificate_id=cert.id, certificate_no=cert.certificate_no,
                supplier_name=cert.supplier.name,
                anomalies=[AnomalyOut(code=a.code, message=a.message) for a in anomalies],
            ))
    return results


@router.post("/certificates/dispatch/bulk", response_model=list[BulkDispatchResultOut])
def bulk_dispatch(body: BulkDispatchRequest, db: Session = Depends(get_db)):
    """Item 10: "Send all" — dispatches every matching certificate with zero
    anomalies by email; anomalous ones are reported as skipped, never
    silently overridden."""
    org = get_org_settings(db)
    channel = DispatchChannel.EMAIL if body.channel == "email" else DispatchChannel.WHATSAPP
    kind = ContactKind.EMAIL if channel == DispatchChannel.EMAIL else ContactKind.WHATSAPP
    certs = _certificates_matching(db, body).all()
    results = []
    for cert in certs:
        anomalies = check_certificate(db, cert, org)
        if anomalies:
            results.append(BulkDispatchResultOut(
                certificate_id=cert.id, certificate_no=cert.certificate_no,
                supplier_name=cert.supplier.name, ok=False,
                error=f"Skipped — {len(anomalies)} anomaly(ies) unresolved",
            ))
            continue
        recipients = [c.value for c in cert.supplier.contacts if c.kind == kind]
        if not recipients:
            results.append(BulkDispatchResultOut(
                certificate_id=cert.id, certificate_no=cert.certificate_no,
                supplier_name=cert.supplier.name, ok=False,
                error=f"No {body.channel} recipients on record",
            ))
            continue
        try:
            jobs = enqueue_dispatch(db, cert, channel, recipients)
            failed = next((j for j in jobs if j.last_error), None)
            results.append(BulkDispatchResultOut(
                certificate_id=cert.id, certificate_no=cert.certificate_no,
                supplier_name=cert.supplier.name, ok=failed is None,
                status=jobs[0].status.value if jobs else None,
                error=failed.last_error if failed else None,
            ))
        except DispatchBlocked as e:
            results.append(BulkDispatchResultOut(
                certificate_id=cert.id, certificate_no=cert.certificate_no,
                supplier_name=cert.supplier.name, ok=False,
                error="; ".join(a.message for a in e.anomalies),
            ))
    return results


@router.get("/certificates/{cert_id}/pdf")
def download_pdf(cert_id: int, db: Session = Depends(get_db)):
    """Serves the PDF for Download and Print actions."""
    cert = db.get(Certificate, cert_id)
    if not cert or not cert.pdf_data:
        raise HTTPException(404, "PDF not found")
    safe_no = (cert.certificate_no or f"cert-{cert.id}").replace("/", "_")
    return Response(content=cert.pdf_data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{safe_no}.pdf"'})


@router.get("/certificates/{cert_id}/image")
def download_certificate_image(cert_id: int, db: Session = Depends(get_db)):
    """Serves the share-ready JPEG (WhatsApp/email/on-screen preview)
    rasterized from the same PDF — pixel-identical to it, not a separate
    render. Self-heals certificates with no image yet by fully re-rendering
    them with the current template — not just rasterizing whatever PDF
    happens to already be stored, which could predate a layout change and
    would otherwise silently reproduce a stale design."""
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if not cert.image_data:
        render_certificate_pdf(db, cert)
        db.commit()
    if not cert.image_data:
        raise HTTPException(404, "Certificate image not found")
    return Response(content=cert.image_data, media_type="image/jpeg")


@router.post("/certificates/{cert_id}/dispatch")
def dispatch(cert_id: int, req: DispatchRequest, db: Session = Depends(get_db)):
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    channel = DispatchChannel.EMAIL if req.channel == "email" else DispatchChannel.WHATSAPP
    kind = ContactKind.EMAIL if channel == DispatchChannel.EMAIL else ContactKind.WHATSAPP
    recipients = req.recipients or [
        c.value for c in cert.supplier.contacts if c.kind == kind
    ]
    if not recipients:
        raise HTTPException(422, f"No {req.channel} recipients on record for supplier")
    try:
        jobs = enqueue_dispatch(db, cert, channel, recipients,
                                override_reason=req.override_reason, user=req.user)
    except DispatchBlocked as e:
        raise HTTPException(
            409,
            detail={"blocked": True,
                    "anomalies": [{"code": a.code, "message": a.message}
                                  for a in e.anomalies]},
        )
    return [{"id": j.id, "recipient": j.recipient, "status": j.status.value,
             "error": j.last_error} for j in jobs]


@router.get("/certificates/{cert_id}/whatsapp-links")
def whatsapp_links(cert_id: int, db: Session = Depends(get_db)):
    """Build free WhatsApp Click-to-Chat links for manual PDF attachment."""
    from urllib.parse import quote

    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if not cert.pdf_data:
        raise HTTPException(422, "Certificate PDF has not been rendered yet")

    org = get_org_settings(db)
    company = cert.company
    officer_name = (company and company.officer_name) or org.officer_name or ""
    company_name = (company and company.name) or org.company_name
    message = (
        f"Dear {cert.supplier.name},\n\n"
        f"Your Certificate of Deduction of Tax {cert.certificate_no} "
        f"for the period {cert.period} is attached.\n\n"
        f"Regards,\n{officer_name}"
        + (f"\n{company_name}" if company_name else "")
    )
    numbers = [c.value for c in cert.supplier.contacts
               if c.kind == ContactKind.WHATSAPP]
    links = []
    for number in numbers:
        digits = "".join(ch for ch in number if ch.isdigit())
        if digits:
            links.append({
                "recipient": number,
                "url": f"https://wa.me/{digits}?text={quote(message)}",
            })
    return {"links": links, "message": message}


@router.post("/dispatch/process")
def process_dispatch_queue(db: Session = Depends(get_db)):
    """Manually drain the offline queue (also runs on a background timer)."""
    return {"processed": process_queue(db)}


@router.get("/dispatch/jobs")
def dispatch_jobs(certificate_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(DispatchJob)
    if certificate_id is not None:
        q = q.filter(DispatchJob.certificate_id == certificate_id)
    jobs = q.order_by(DispatchJob.created_at.desc()).limit(100).all()
    return [{"id": j.id, "certificate_id": j.certificate_id,
             "channel": j.channel.value, "recipient": j.recipient,
             "status": j.status.value, "attempts": j.attempts,
             "last_error": j.last_error, "opened_at": j.opened_at} for j in jobs]


# -------------------------------------------------------------- Suppliers ----
@router.post("/suppliers", response_model=SupplierOut)
def onboard_supplier(body: SupplierCreate, db: Session = Depends(get_db)):
    """Vendor onboarding: Company Name, Address, TIN, BIN, Email, WhatsApp
    are all mandatory (enforced by SupplierCreate's validators). Upserts by
    (company_id, TIN), mirroring the dedup convention the Excel importer
    already uses — the same TIN can independently exist under two companies."""
    sup = (
        db.query(Supplier)
        .filter(Supplier.company_id == body.company_id, Supplier.tin == body.tin)
        .first()
    )
    if sup:
        sup.name = body.name
        sup.address = body.address
        sup.bin = body.bin
    else:
        sup = Supplier(company_id=body.company_id, tin=body.tin, name=body.name,
                       address=body.address, bin=body.bin)
        db.add(sup)
        db.flush()

    for kind, value in ((ContactKind.EMAIL, body.email), (ContactKind.WHATSAPP, body.whatsapp)):
        existing = next((c for c in sup.contacts if c.kind == kind), None)
        if existing:
            existing.value = value
            existing.is_primary = True
        else:
            sup.contacts.append(SupplierContact(kind=kind, value=value, is_primary=True))
    db.commit()
    db.refresh(sup)
    return sup


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(company_id: int, q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Supplier).filter(Supplier.company_id == company_id)
    if q:
        query = query.filter(or_(Supplier.name.ilike(f"%{q}%"),
                                 Supplier.tin.like(f"%{q}%"),
                                 Supplier.bin.like(f"%{q}%")))
    return query.order_by(Supplier.name).limit(100).all()


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, body: SupplierUpdate, db: Session = Depends(get_db)):
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise HTTPException(404, "Supplier not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(sup, field, value)
    db.commit()
    return sup


@router.post("/suppliers/{supplier_id}/contacts", response_model=SupplierOut)
def add_contact(supplier_id: int, body: ContactCreate, db: Session = Depends(get_db)):
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise HTTPException(404, "Supplier not found")
    db.add(SupplierContact(supplier_id=supplier_id,
                           kind=ContactKind(body.kind), value=body.value,
                           is_primary=body.is_primary))
    db.commit()
    db.refresh(sup)
    return sup


# --------------------------------------------------------------- Settings ----
_ORG_BINARY_FIELDS = {"logo_data", "seal_signature_data", "signature_data", "seal_data"}


@router.get("/settings/org")
def get_org(db: Session = Depends(get_db)):
    s = get_org_settings(db)
    db.commit()
    # Raw image bytes are never inlined into JSON — fetched separately via
    # the dedicated image routes. Booleans stand in for "is one uploaded".
    data = {c.name: getattr(s, c.name) for c in s.__table__.columns
            if c.name not in _ORG_BINARY_FIELDS}
    for field in _ORG_BINARY_FIELDS:
        data[f"has_{field[:-5]}"] = bool(getattr(s, field))
    data["smtp_password"] = bool(data.get("smtp_password"))  # never echo secrets
    data["wa_token"] = bool(data.get("wa_token"))
    data["wa_twilio_auth"] = bool(data.get("wa_twilio_auth"))
    return data


@router.put("/settings/org")
def update_org(body: OrgSettingsIn, db: Session = Depends(get_db)):
    s = get_org_settings(db)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(s, field, value)
    db.commit()
    return {"ok": True}


@router.post("/settings/org/test-email")
def test_email(db: Session = Depends(get_db)):
    s = get_org_settings(db)
    try:
        recipient = send_test_email(s)
    except RuntimeError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "recipient": recipient}


@router.post("/settings/org/logo")
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await _store_image(db, file, "logo_data")


@router.post("/settings/org/seal")
async def upload_seal(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Seal + signature image — PNG with transparency recommended."""
    _require_image(file)
    return await _store_image(db, file, "seal_signature_data")


@router.get("/settings/org/logo")
def get_logo(db: Session = Depends(get_db)):
    org = get_org_settings(db)
    if not org.logo_data:
        raise HTTPException(404, "No logo uploaded")
    return Response(content=org.logo_data, media_type=_sniff_image_mime(org.logo_data))


@router.get("/settings/org/seal")
def get_seal(db: Session = Depends(get_db)):
    org = get_org_settings(db)
    if not org.seal_signature_data:
        raise HTTPException(404, "No seal/signature uploaded")
    return Response(content=org.seal_signature_data, media_type=_sniff_image_mime(org.seal_signature_data))


@router.post("/settings/org/signature")
async def upload_signature(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Signature image, separate from the seal image (item 8)."""
    _require_image(file)
    return await _store_image(db, file, "signature_data")


@router.get("/settings/org/signature")
def get_signature(db: Session = Depends(get_db)):
    org = get_org_settings(db)
    if not org.signature_data:
        raise HTTPException(404, "No signature uploaded")
    return Response(content=org.signature_data, media_type=_sniff_image_mime(org.signature_data))


@router.post("/settings/org/seal-image")
async def upload_seal_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Seal image, separate from the signature image (item 8)."""
    _require_image(file)
    return await _store_image(db, file, "seal_data")


@router.get("/settings/org/seal-image")
def get_seal_image(db: Session = Depends(get_db)):
    org = get_org_settings(db)
    if not org.seal_data:
        raise HTTPException(404, "No seal uploaded")
    return Response(content=org.seal_data, media_type=_sniff_image_mime(org.seal_data))


async def _store_image(db: Session, file: UploadFile, attr: str):
    data = await file.read()
    s = get_org_settings(db)
    setattr(s, attr, data)
    db.commit()
    return {"ok": True}


# -------------------------------------------------------------- Companies ----
@router.get("/companies", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.query(Company).order_by(Company.id).all()


@router.post("/companies", response_model=CompanyOut)
def create_company(body: CompanyCreate, db: Session = Depends(get_db)):
    if body.is_default:
        db.query(Company).update({Company.is_default: False})
    company = Company(**body.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: int, body: CompanyUpdate, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    if body.is_default:
        db.query(Company).update({Company.is_default: False})
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(company, field, value)
    db.commit()
    db.refresh(company)
    return company


@router.post("/companies/{company_id}/seal")
async def upload_company_seal(company_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_image(file)
    return await _store_company_image(db, company_id, file, "seal_data")


@router.get("/companies/{company_id}/seal")
def get_company_seal(company_id: int, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    if not company.seal_data:
        raise HTTPException(404, "No seal uploaded")
    return Response(content=company.seal_data, media_type=_sniff_image_mime(company.seal_data))


@router.post("/companies/{company_id}/letterhead/header")
async def upload_letterhead_header(company_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_image(file)
    return await _store_company_image(db, company_id, file, "letterhead_header_data")


@router.get("/companies/{company_id}/letterhead/header")
def get_letterhead_header(company_id: int, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    if not company.letterhead_header_data:
        raise HTTPException(404, "No letterhead header uploaded")
    return Response(content=company.letterhead_header_data,
                    media_type=_sniff_image_mime(company.letterhead_header_data))


@router.post("/companies/{company_id}/letterhead/footer")
async def upload_letterhead_footer(company_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_image(file)
    return await _store_company_image(db, company_id, file, "letterhead_footer_data")


@router.get("/companies/{company_id}/letterhead/footer")
def get_letterhead_footer(company_id: int, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    if not company.letterhead_footer_data:
        raise HTTPException(404, "No letterhead footer uploaded")
    return Response(content=company.letterhead_footer_data,
                    media_type=_sniff_image_mime(company.letterhead_footer_data))


def _require_image(file: UploadFile):
    if file.content_type not in ("image/png", "image/jpeg"):
        raise HTTPException(422, "Upload a PNG (preferred, supports transparency) or JPEG")


async def _store_company_image(db: Session, company_id: int, file: UploadFile, attr: str):
    company = get_company(db, company_id)
    data = await file.read()
    setattr(company, attr, data)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------- Signatures ----
@router.get("/companies/{company_id}/signatures", response_model=list[SignatureOut])
def list_signatures(company_id: int, db: Session = Depends(get_db)):
    return (db.query(Signature).filter(Signature.company_id == company_id)
            .order_by(Signature.name).all())


@router.post("/companies/{company_id}/signatures", response_model=SignatureOut)
async def create_signature(company_id: int, name: str = Form(...),
                           designation: str | None = Form(None),
                           email: str | None = Form(None),
                           file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Multiple named signatures per company; every one flagged `enabled`
    renders on every certificate generated for that company."""
    get_company(db, company_id)  # 404s if the company doesn't exist
    _require_image(file)
    data = await file.read()

    sig = Signature(company_id=company_id, name=name, designation=designation,
                    email=email, image_data=data, enabled=True)
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return sig


@router.get("/companies/{company_id}/signatures/{signature_id}/image")
def get_signature_image(company_id: int, signature_id: int, db: Session = Depends(get_db)):
    sig = db.get(Signature, signature_id)
    if not sig or sig.company_id != company_id or not sig.image_data:
        raise HTTPException(404, "Signature image not found")
    return Response(content=sig.image_data, media_type=_sniff_image_mime(sig.image_data))


@router.patch("/companies/{company_id}/signatures/{signature_id}", response_model=SignatureOut)
def update_signature(company_id: int, signature_id: int, body: SignatureUpdate,
                     db: Session = Depends(get_db)):
    sig = db.get(Signature, signature_id)
    if not sig or sig.company_id != company_id:
        raise HTTPException(404, "Signature not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(sig, field, value)
    db.commit()
    db.refresh(sig)
    return sig


@router.delete("/companies/{company_id}/signatures/{signature_id}")
def delete_signature(company_id: int, signature_id: int, db: Session = Depends(get_db)):
    sig = db.get(Signature, signature_id)
    if not sig or sig.company_id != company_id:
        raise HTTPException(404, "Signature not found")
    db.delete(sig)
    db.commit()
    return {"ok": True}


@router.get("/companies/{company_id}/numbering")
def get_numbering(company_id: int, db: Session = Depends(get_db)):
    cfg = get_numbering_config(db, company_id)
    db.commit()
    return {c.name: getattr(cfg, c.name) for c in cfg.__table__.columns}


@router.put("/companies/{company_id}/numbering")
def update_numbering(company_id: int, body: NumberingIn, db: Session = Depends(get_db)):
    cfg = get_numbering_config(db, company_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cfg, field, value)
    db.commit()
    return {"ok": True}


@router.post("/settings/database/reset")
def reset_database(body: DatabaseResetRequest, db: Session = Depends(get_db)):
    """Clear all module data so the app can start from a blank state.

    Requires confirm == "RESET" server-side — the frontend's confirmation
    typing is client-side only and doesn't protect the endpoint on its own.
    """
    if body.confirm != "RESET":
        raise HTTPException(400, "Type RESET to confirm database reset")
    models = [
        OverrideLog,
        DispatchJob,
        CertificateChallanLine,
        CertificateLine,
        Certificate,
        Transaction,
        SupplierContact,
        Supplier,
        ImportRowError,
        ImportBatch,
        RateAnomaly,
        TaxRate,
        NumberSequence,
        NumberingConfig,
        Signature,
        Company,
        OrgSettings,
    ]
    deleted = {}
    for model in models:
        deleted[model.__tablename__] = db.query(model).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": deleted}


# ------------------------------------------------------------- Rate hook ----
@router.post("/rates/update")
def rates_update(updates: list[RateUpdateIn], db: Session = Depends(get_db)):
    """Service interface for the existing rate-scraper automation."""
    result = rate_hook.apply_rate_updates(
        db, [rate_hook.RateUpdate(**u.model_dump()) for u in updates])
    return result


@router.post("/rates/scrape-failure")
def rates_scrape_failure(payload: dict, db: Session = Depends(get_db)):
    rate_hook.report_scrape_failure(db, payload.get("message", "unknown"))
    return {"ok": True}


@router.get("/rates/anomalies")
def rates_anomalies(db: Session = Depends(get_db)):
    rows = (db.query(RateAnomaly).filter(RateAnomaly.resolved.is_(False))
            .order_by(RateAnomaly.created_at.desc()).limit(100).all())
    return [{"id": r.id, "section": r.section, "kind": r.kind,
             "message": r.message, "created_at": r.created_at} for r in rows]


# -------------------------------------------------------------- Dashboard ----
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """Summary/overview only — deliberately NO recent journal entries."""
    total_txn = db.query(func.count(Transaction.id)).scalar() or 0
    total_suppliers = db.query(func.count(Supplier.id)).scalar() or 0
    certs = db.query(Certificate.status, func.count(Certificate.id)).group_by(
        Certificate.status).all()
    cert_counts = {s.value if hasattr(s, "value") else str(s): n for s, n in certs}
    pending = len(pending_groupings(db=db))
    tds_total = db.query(func.sum(Transaction.sum_of_tds)).scalar() or 0
    queued = (db.query(func.count(DispatchJob.id))
              .filter(DispatchJob.status == "queued").scalar() or 0)
    return {
        "transactions": total_txn,
        "suppliers": total_suppliers,
        "certificates": cert_counts,
        "pending_groupings": pending,
        "total_tds": round(tds_total, 2),
        "queued_dispatches": queued,
    }


# ------------------------------------------------- Public hosted PDF link ----
public_router = APIRouter()


@public_router.get("/public/certificates/{cert_id}")
def public_certificate(cert_id: int, sig: str, db: Session = Depends(get_db)):
    """Signed hosted link used by WhatsApp document messages."""
    if not verify_certificate_sig(cert_id, sig):
        raise HTTPException(403, "Invalid link signature")
    cert = db.get(Certificate, cert_id)
    if not cert or not cert.pdf_data:
        raise HTTPException(404, "Not found")
    return Response(content=cert.pdf_data, media_type="application/pdf")


# 1x1 transparent PNG, served only if no org logo/signature has been uploaded.
_BLANK_PIXEL = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@public_router.get("/public/track/{job_id}.png")
def track_email_open(job_id: int, sig: str, db: Session = Depends(get_db)):
    """Email open-tracking beacon: the org logo/signature, loaded from a
    per-dispatch signed URL so viewing the email marks the job as opened."""
    if not verify_job_sig(job_id, sig):
        raise HTTPException(403, "Invalid link signature")
    job = db.get(DispatchJob, job_id)
    if job and job.opened_at is None:
        job.opened_at = datetime.utcnow()
        db.commit()
    org = get_org_settings(db)
    for data in (org.logo_data, org.seal_signature_data):
        if data:
            return Response(content=data, media_type=_sniff_image_mime(data))
    return Response(content=_BLANK_PIXEL, media_type="image/png")
