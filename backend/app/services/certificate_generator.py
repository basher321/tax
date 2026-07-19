"""Certificate generation: one certificate per unique (TIN, period).

Enforces supplier/vendor-only generation at the service level, allocates the
certificate number atomically, snapshots line items, and renders the PDF.
"""
from datetime import date

from sqlalchemy.orm import Session

from ..models.entities import (
    Certificate,
    CertificateChallanLine,
    CertificateLine,
    CertStatus,
    Company,
    OrgSettings,
    PartyType,
    Supplier,
)
from .aggregation import build_certificate_data
from .amount_in_words import amount_in_words
from .numbering import allocate_certificate_number
from .pdf_renderer import render_certificate_pdf


class GenerationError(Exception):
    pass


def get_org_settings(db: Session) -> OrgSettings:
    s = db.get(OrgSettings, 1)
    if not s:
        s = OrgSettings(id=1)
        db.add(s)
        db.flush()
    return s


def get_company(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise GenerationError(f"No company with id {company_id}")
    return company


def generate_certificate(db: Session, company_id: int, tin: str, period: str) -> Certificate:
    existing = (
        db.query(Certificate)
        .filter(Certificate.company_id == company_id, Certificate.tin == tin,
                Certificate.period == period, Certificate.status != CertStatus.VOID)
        .first()
    )
    if existing:
        raise GenerationError(
            f"Certificate already exists for TIN {tin} / period {period} "
            f"({existing.certificate_no})"
        )

    company = get_company(db, company_id)
    data = build_certificate_data(
        db, company_id, tin, period,
        default_description=company.default_description or "Supply of Goods",
        default_bank=company.default_bank_name,
    )
    if data is None:
        raise GenerationError(f"No transactions found for TIN {tin} / {period}")

    # --- supplier/vendor-only rule, enforced HERE (not just in the UI) ---
    supplier = db.get(Supplier, data.supplier_id) if data.supplier_id else None
    if supplier is None:
        raise GenerationError(f"No supplier record for TIN {tin}")
    if supplier.party_type != PartyType.SUPPLIER:
        raise GenerationError(
            f"Refusing to generate: party {supplier.name} is "
            f"'{supplier.party_type.value}', certificates are supplier-only."
        )

    cert_no = allocate_certificate_number(db, company_id, period)

    cert = Certificate(
        certificate_no=cert_no,
        company_id=company_id,
        supplier_id=supplier.id,
        tin=tin,
        period=period,
        period_from=data.period_from,
        period_to=data.period_to,
        total_payment=data.total_payment,
        total_tax_deducted=data.total_tax_deducted,
        total_vds=data.total_vds,
        amount_in_words=amount_in_words(data.total_tax_deducted),
        has_12_digit_tin=bool(tin and len(tin) == 12),
        status=CertStatus.GENERATED,
        issue_date=date.today(),
        issue_date_mode="auto",
    )
    db.add(cert)
    db.flush()

    for ln in data.lines:
        db.add(CertificateLine(
            certificate_id=cert.id, sl=ln.sl,
            date_of_payment=ln.date_of_payment, description=ln.description,
            section=ln.section, amount_of_payment=ln.amount_of_payment,
            amount_of_tax_deducted=ln.amount_of_tax_deducted,
        ))
    for cl in data.challan_lines:
        db.add(CertificateChallanLine(
            certificate_id=cert.id, sl=cl.sl,
            challan_number=cl.challan_number, challan_date=cl.challan_date,
            bank_name=cl.bank_name,
            total_challan_amount=cl.total_challan_amount,
            amount_related=cl.amount_related,
        ))
    db.flush()

    render_certificate_pdf(db, cert)  # sets cert.pdf_data / cert.image_data
    db.commit()
    return cert


def regenerate_pdf(db: Session, cert: Certificate) -> None:
    """Re-render after a Remarks edit — data lines are immutable."""
    render_certificate_pdf(db, cert)  # sets cert.pdf_data / cert.image_data
    db.commit()
