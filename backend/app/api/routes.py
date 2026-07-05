"""All API routers for the module, mounted under /api."""
import os
import shutil
import tempfile
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models.entities import (
    Certificate,
    CertStatus,
    ContactKind,
    DispatchChannel,
    DispatchJob,
    ImportBatch,
    RateAnomaly,
    Supplier,
    SupplierContact,
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
from ..services.dispatch.whatsapp_sender import verify_certificate_sig
from ..services.excel_import import import_challan_file, import_depot_workbook
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
    path = _save_upload(file)
    try:
        return import_depot_workbook(db, path, file.filename or "upload.xlsx")
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        os.unlink(path)


@router.post("/import/challan", response_model=ImportBatchOut)
def upload_challan(file: UploadFile = File(...), db: Session = Depends(get_db)):
    path = _save_upload(file)
    try:
        return import_challan_file(db, path, file.filename or "challan.xlsx")
    finally:
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
    if date_from:
        q = q.filter(Certificate.issue_date >= date_from)
    if date_to:
        q = q.filter(Certificate.issue_date <= date_to)
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
    """Remarks is the ONLY editable field. Everything else is read-only."""
    cert = db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    cert.remarks = body.remarks
    regenerate_pdf(db, cert)  # re-render so the PDF reflects the new remarks
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
    return [{"id": j.id, "recipient": j.recipient, "status": j.status.value}
            for j in jobs]


@router.post("/dispatch/process")
def process_dispatch_queue(db: Session = Depends(get_db)):
    """Manually drain the offline queue (also runs on a background timer)."""
    return {"processed": process_queue(db)}


@router.get("/dispatch/jobs")
def dispatch_jobs(db: Session = Depends(get_db)):
    jobs = (db.query(DispatchJob).order_by(DispatchJob.created_at.desc())
            .limit(100).all())
    return [{"id": j.id, "certificate_id": j.certificate_id,
             "channel": j.channel.value, "recipient": j.recipient,
             "status": j.status.value, "attempts": j.attempts,
             "last_error": j.last_error} for j in jobs]


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


@router.post("/settings/org/logo")
def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return _store_image(db, file, "logo_path", "logo")


@router.post("/settings/org/seal")
def upload_seal(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Seal + signature image — PNG with transparency recommended."""
    if file.content_type not in ("image/png", "image/jpeg"):
        raise HTTPException(422, "Upload a PNG (preferred, supports transparency) or JPEG")
    return _store_image(db, file, "seal_signature_path", "seal_signature")


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
