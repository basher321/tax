"""All API routers for the module, mounted under /api."""
import os
import shutil
import tempfile
from zipfile import BadZipFile
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, func, or_, true
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models.entities import (
    Certificate,
    CertificateChallanLine,
    CertificateLine,
    CertStatus,
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
    Supplier,
    SupplierContact,
    TaxRate,
    Transaction,
)
from ..schemas import (
    AnomalyOut,
    BulkGenerateRequest,
    CertificateDetailOut,
    CertificateOut,
    ContactCreate,
    DispatchRequest,
    GenerateRequest,
    ImportBatchOut,
    NumberingIn,
    OrgSettingsIn,
    RateUpdateIn,
    RemarksUpdate,
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
    get_org_settings,
    regenerate_pdf,
)
from ..services.dispatch import DispatchBlocked, enqueue_dispatch, process_queue
from ..services.dispatch.email_sender import send_test_email, verify_job_sig
from ..services.dispatch.whatsapp_sender import verify_certificate_sig
from ..services.excel_import import import_depot_workbook, load_depot_sheet
from ..services.numbering import get_numbering_config
from ..services.validation import check_certificate

router = APIRouter(prefix="/api")


def _save_upload(upload: UploadFile) -> str:
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(upload.filename or "")[1])
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return path


# ---------------------------------------------------------------- Import ----
@router.post("/import/depot", response_model=ImportBatchOut)
def upload_depot(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Upload an .xlsx workbook")
    path = _save_upload(file)
    try:
        batch = import_depot_workbook(db, path, file.filename or "upload.xlsx")
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
def list_batches(db: Session = Depends(get_db)):
    return db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50).all()


# ---------------------------------------------------------- Certificates ----
@router.get("/certificates/pending")
def pending_groupings(db: Session = Depends(get_db)):
    """(TIN, period) groupings with no certificate yet."""
    issued = {
        (c.tin, c.period)
        for c in db.query(Certificate).filter(Certificate.status != CertStatus.VOID)
    }
    return [g for g in list_groupings(db) if (g["tin"], g["period"]) not in issued]


@router.get("/certificates")
def search_certificates(
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
    q = db.query(Certificate).join(Supplier)
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
        return generate_certificate(db, req.tin, req.period)
    except GenerationError as e:
        raise HTTPException(409, str(e))


@router.post("/certificates/generate/bulk")
def generate_bulk(req: BulkGenerateRequest, db: Session = Depends(get_db)):
    results = []
    for item in req.items:
        try:
            cert = generate_certificate(db, item.tin, item.period)
            results.append({"tin": item.tin, "period": item.period,
                            "ok": True, "certificate_no": cert.certificate_no})
        except GenerationError as e:
            db.rollback()
            results.append({"tin": item.tin, "period": item.period,
                            "ok": False, "error": str(e)})
    return results


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


@router.get("/certificates/{cert_id}/anomalies", response_model=list[AnomalyOut])
def certificate_anomalies(cert_id: int, db: Session = Depends(get_db)):
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    org = get_org_settings(db)
    return [AnomalyOut(code=a.code, message=a.message)
            for a in check_certificate(db, cert, org)]


@router.get("/certificates/{cert_id}/pdf")
def download_pdf(cert_id: int, db: Session = Depends(get_db)):
    """Serves the PDF for Download and Print actions."""
    cert = db.get(Certificate, cert_id)
    if not cert or not cert.pdf_path or not os.path.exists(cert.pdf_path):
        raise HTTPException(404, "PDF not found")
    return FileResponse(cert.pdf_path, media_type="application/pdf",
                        filename=os.path.basename(cert.pdf_path))


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
    if not cert.pdf_path or not os.path.exists(cert.pdf_path):
        raise HTTPException(422, "Certificate PDF has not been rendered yet")

    org = get_org_settings(db)
    message = (
        f"Dear {cert.supplier.name},\n\n"
        f"Your Certificate of Deduction of Tax {cert.certificate_no} "
        f"for the period {cert.period} is attached.\n\n"
        f"Regards,\n{org.officer_name or ''}"
        + (f"\n{org.company_name}" if org.company_name else "")
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
@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Supplier)
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
@router.get("/settings/org")
def get_org(db: Session = Depends(get_db)):
    s = get_org_settings(db)
    db.commit()
    data = {c.name: getattr(s, c.name) for c in s.__table__.columns}
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
def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return _store_image(db, file, "logo_path", "logo")


@router.post("/settings/org/seal")
def upload_seal(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Seal + signature image — PNG with transparency recommended."""
    if file.content_type not in ("image/png", "image/jpeg"):
        raise HTTPException(422, "Upload a PNG (preferred, supports transparency) or JPEG")
    return _store_image(db, file, "seal_signature_path", "seal_signature")


@router.get("/settings/org/logo")
def get_logo(db: Session = Depends(get_db)):
    org = get_org_settings(db)
    if not org.logo_path or not os.path.exists(org.logo_path):
        raise HTTPException(404, "No logo uploaded")
    return FileResponse(org.logo_path)


@router.get("/settings/org/seal")
def get_seal(db: Session = Depends(get_db)):
    org = get_org_settings(db)
    if not org.seal_signature_path or not os.path.exists(org.seal_signature_path):
        raise HTTPException(404, "No seal/signature uploaded")
    return FileResponse(org.seal_signature_path)


def _store_image(db: Session, file: UploadFile, attr: str, name: str):
    settings = get_settings()
    img_dir = os.path.join(settings.storage_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".png"
    path = os.path.join(img_dir, f"{name}{ext}")
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    s = get_org_settings(db)
    setattr(s, attr, path)
    db.commit()
    return {"ok": True, "path": path}


@router.get("/settings/numbering")
def get_numbering(db: Session = Depends(get_db)):
    cfg = get_numbering_config(db)
    db.commit()
    return {c.name: getattr(cfg, c.name) for c in cfg.__table__.columns}


@router.put("/settings/numbering")
def update_numbering(body: NumberingIn, db: Session = Depends(get_db)):
    cfg = get_numbering_config(db)
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
    pending = len(pending_groupings(db))
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
    if not cert or not cert.pdf_path or not os.path.exists(cert.pdf_path):
        raise HTTPException(404, "Not found")
    return FileResponse(cert.pdf_path, media_type="application/pdf")


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
    for path in (org.logo_path, org.seal_signature_path):
        if path and os.path.exists(path):
            return FileResponse(path)
    return Response(content=_BLANK_PIXEL, media_type="image/png")
