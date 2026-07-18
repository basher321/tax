"""Pre-dispatch anomaly checks.

Every check returns a code + human message. Dispatch is blocked while any
anomaly exists, unless the user overrides with a logged reason (OverrideLog).
"""
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models.entities import (
    Certificate,
    CertStatus,
    ContactKind,
    OrgSettings,
    TaxRate,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d{10,15}$")
RATE_TOLERANCE = 0.02  # 2% absolute tolerance on effective rate reconciliation


@dataclass
class Anomaly:
    code: str
    message: str


def _supplier_contacts(cert: Certificate, kind: ContactKind) -> list[str]:
    return [c.value for c in cert.supplier.contacts if c.kind == kind]


def check_certificate(db: Session, cert: Certificate, org: OrgSettings) -> list[Anomaly]:
    anomalies: list[Anomaly] = []

    # --- contactability ---
    emails = _supplier_contacts(cert, ContactKind.EMAIL)
    if not emails:
        anomalies.append(Anomaly("MISSING_EMAIL", "Supplier has no email address"))
    else:
        bad = [e for e in emails if not EMAIL_RE.match(e)]
        if bad:
            anomalies.append(Anomaly("INVALID_EMAIL", f"Invalid email(s): {', '.join(bad)}"))

    phones = _supplier_contacts(cert, ContactKind.WHATSAPP)
    if not phones:
        anomalies.append(Anomaly("MISSING_WHATSAPP", "Supplier has no WhatsApp number"))
    else:
        bad = [p for p in phones if not PHONE_RE.match(re.sub(r"[\s-]", "", p))]
        if bad:
            anomalies.append(Anomaly("INVALID_WHATSAPP",
                                     f"Invalid WhatsApp number(s): {', '.join(bad)}"))

    # --- identity ---
    if not cert.tin:
        anomalies.append(Anomaly("MISSING_TIN", "Certificate has no TIN"))

    # --- challan mapping ---
    unmapped = [ln.sl for ln in cert.challan_lines if not ln.challan_number]
    if unmapped:
        anomalies.append(Anomaly(
            "MISSING_CHALLAN",
            f"{len(unmapped)} line(s) have no challan mapping (Sl: "
            f"{', '.join(map(str, unmapped[:10]))}{'…' if len(unmapped) > 10 else ''})"))

    # --- TDS reconciliation against expected section rates ---
    for ln in cert.lines:
        if not ln.section or not ln.amount_of_payment:
            continue
        rate_row = (
            db.query(TaxRate)
            .filter(TaxRate.section == str(ln.section), TaxRate.kind == "tds")
            .order_by(TaxRate.effective_from.desc())
            .first()
        )
        if not rate_row:
            continue  # missing-rate anomalies are raised by the rate hook
        expected = ln.amount_of_payment * rate_row.rate
        actual = ln.amount_of_tax_deducted or 0
        if ln.amount_of_payment > 0:
            eff = actual / ln.amount_of_payment
            if abs(eff - rate_row.rate) > RATE_TOLERANCE:
                anomalies.append(Anomaly(
                    "TDS_MISMATCH",
                    f"Sl {ln.sl}: TDS {actual:,.2f} implies rate {eff:.2%}, "
                    f"expected {rate_row.rate:.2%} for section {ln.section} "
                    f"(expected amount ≈ {expected:,.2f})"))

    # --- duplicate (TIN, period), scoped to the same company ---
    dup = (
        db.query(Certificate)
        .filter(Certificate.company_id == cert.company_id, Certificate.tin == cert.tin,
                Certificate.period == cert.period,
                Certificate.id != cert.id, Certificate.status != CertStatus.VOID)
        .first()
    )
    if dup:
        anomalies.append(Anomaly(
            "DUPLICATE_CERT",
            f"Another certificate exists for TIN {cert.tin} / {cert.period}: "
            f"{dup.certificate_no}"))

    # --- company settings completeness (falls back to the legacy singleton
    # org fields for a company that hasn't set its own yet) ---
    company = cert.company
    has_seal = bool(
        company and company.seal_path
        or org.seal_signature_path or (org.signature_path and org.seal_path)
    )
    if not has_seal:
        anomalies.append(Anomaly("MISSING_SEAL", "Seal/signature image not uploaded in Settings"))
    officer_name = (company and company.officer_name) or org.officer_name
    officer_designation = (company and company.officer_designation) or org.officer_designation
    officer_email = (company and company.officer_email) or org.officer_email
    if not (officer_name and officer_designation and officer_email):
        anomalies.append(Anomaly("MISSING_OFFICER", "Designated officer details incomplete in Settings"))

    return anomalies
