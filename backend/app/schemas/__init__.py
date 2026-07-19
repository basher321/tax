import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator

# Shared with services/validation.py's anomaly checks; kept in sync manually
# since schemas has no dependency on services.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{10,15}$")
_TIN_12_RE = re.compile(r"^\d{12}$")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ContactOut(ORM):
    id: int
    kind: str
    value: str
    is_primary: bool


class SupplierOut(ORM):
    id: int
    tin: str
    bin: str | None
    name: str
    address: str | None
    party_type: str
    contacts: list[ContactOut] = []


class SupplierUpdate(BaseModel):
    bin: str | None = None
    name: str | None = None
    address: str | None = None
    party_type: str | None = None


class SupplierCreate(BaseModel):
    """Vendor onboarding: all six fields are mandatory and validated here as
    well as client-side — the client check alone never protects the API."""

    company_id: int
    name: str
    address: str
    tin: str
    bin: str
    email: str
    whatsapp: str

    @field_validator("name", "address", "bin")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field is required")
        return v

    @field_validator("tin")
    @classmethod
    def _tin_12_digits(cls, v: str) -> str:
        v = re.sub(r"\D", "", v or "")
        if not _TIN_12_RE.match(v):
            raise ValueError("TIN must be exactly 12 digits")
        return v

    @field_validator("email")
    @classmethod
    def _email_format(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("whatsapp")
    @classmethod
    def _whatsapp_format(cls, v: str) -> str:
        v = v.strip()
        if not _PHONE_RE.match(re.sub(r"[\s-]", "", v)):
            raise ValueError("Enter a valid WhatsApp number (10-15 digits)")
        return v


class ContactCreate(BaseModel):
    kind: str  # email | whatsapp
    value: str
    is_primary: bool = False


class ImportErrorOut(ORM):
    row_number: int
    column: str | None
    message: str


class ImportBatchOut(ORM):
    id: int
    filename: str
    kind: str
    total_rows: int
    ok_rows: int
    error_rows: int
    created_at: datetime
    errors: list[ImportErrorOut] = []
    rows: list[dict] | None = None
    columns: list[str] | None = None


class CertLineOut(ORM):
    sl: int
    date_of_payment: date | None
    description: str | None
    section: str | None
    amount_of_payment: float | None
    amount_of_tax_deducted: float | None
    remarks: str | None


class ChallanLineOut(ORM):
    sl: int
    challan_number: str | None
    challan_date: date | None
    bank_name: str | None
    total_challan_amount: float | None
    amount_related: float | None
    remarks: str | None


class CertificateOut(ORM):
    id: int
    company_id: int
    certificate_no: str | None
    tin: str
    period: str
    period_from: date | None
    period_to: date | None
    total_payment: float
    total_tax_deducted: float
    amount_in_words: str | None
    remarks: str | None
    has_12_digit_tin: bool
    status: str
    issue_date: date
    issue_date_mode: str
    supplier: SupplierOut


class CertificateDetailOut(CertificateOut):
    lines: list[CertLineOut] = []
    challan_lines: list[ChallanLineOut] = []


class RemarksUpdate(BaseModel):
    remarks: str | None = None


class TinStatusUpdate(BaseModel):
    has_12_digit_tin: bool


class DatabaseResetRequest(BaseModel):
    confirm: str


class GenerateRequest(BaseModel):
    company_id: int
    tin: str
    period: str


class BulkGenerateRequest(BaseModel):
    items: list[GenerateRequest]


class IssueDateUpdate(BaseModel):
    """Item 4: preview lets the user pick automatic (today) or manual date."""

    mode: str  # "auto" | "manual"
    issue_date: date | None = None  # required when mode == "manual"

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in ("auto", "manual"):
            raise ValueError("mode must be 'auto' or 'manual'")
        return v


class DispatchRequest(BaseModel):
    channel: str  # email | whatsapp
    recipients: list[str] | None = None  # default: all supplier contacts of kind
    override_reason: str | None = None
    user: str | None = None


class AnomalyOut(BaseModel):
    code: str
    message: str


class CompanyOut(ORM):
    id: int
    name: str
    address: str | None
    has_seal: bool
    has_letterhead_header: bool
    has_letterhead_footer: bool
    officer_name: str | None
    officer_designation: str | None
    officer_email: str | None
    default_bank_name: str | None
    default_description: str | None
    is_default: bool


class CompanyCreate(BaseModel):
    name: str
    address: str | None = None
    officer_name: str | None = None
    officer_designation: str | None = None
    officer_email: str | None = None
    default_bank_name: str | None = None
    default_description: str | None = None
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Company name is required")
        return v


class CompanyUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    officer_name: str | None = None
    officer_designation: str | None = None
    officer_email: str | None = None
    default_bank_name: str | None = None
    default_description: str | None = None
    is_default: bool | None = None


class SignatureOut(ORM):
    id: int
    company_id: int
    name: str
    designation: str | None
    email: str | None
    enabled: bool


class SignatureUpdate(BaseModel):
    name: str | None = None
    designation: str | None = None
    email: str | None = None
    enabled: bool | None = None


class BulkFilterRequest(BaseModel):
    """Shared filter shape for the bulk anomaly check (item 5) and bulk send
    (item 10) — mirrors the query params of GET /certificates."""

    company_id: int
    tin: str | None = None
    bin: str | None = None
    supplier_name: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None


class BulkAnomalyOut(BaseModel):
    certificate_id: int
    certificate_no: str | None
    supplier_name: str
    anomalies: list[AnomalyOut]


class BulkDispatchRequest(BulkFilterRequest):
    channel: str = "email"


class BulkDispatchResultOut(BaseModel):
    certificate_id: int
    certificate_no: str | None
    supplier_name: str
    ok: bool
    status: str | None = None
    error: str | None = None


class OrgSettingsIn(BaseModel):
    company_name: str | None = None
    company_address: str | None = None
    officer_name: str | None = None
    officer_designation: str | None = None
    officer_email: str | None = None
    default_bank_name: str | None = None
    default_description: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    smtp_from: str | None = None
    wa_provider: str | None = None
    wa_token: str | None = None
    wa_phone_number_id: str | None = None
    wa_twilio_sid: str | None = None
    wa_twilio_auth: str | None = None
    wa_twilio_from: str | None = None
    dispatch_mode: str | None = None


class NumberingIn(BaseModel):
    company_token: str | None = None
    fiscal_year_format: str | None = None
    pad_width: int | None = None
    start_number: int | None = None
    reset_policy: str | None = None
    separator: str | None = None
    number_format: str | None = None


class RateUpdateIn(BaseModel):
    section: str
    kind: str
    rate: float
    effective_from: date | None = None
    source: str = "scraper"
