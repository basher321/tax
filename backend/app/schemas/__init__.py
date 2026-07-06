from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


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
    tin: str
    period: str


class BulkGenerateRequest(BaseModel):
    items: list[GenerateRequest]


class DispatchRequest(BaseModel):
    channel: str  # email | whatsapp
    recipients: list[str] | None = None  # default: all supplier contacts of kind
    override_reason: str | None = None
    user: str | None = None


class AnomalyOut(BaseModel):
    code: str
    message: str


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


class RateUpdateIn(BaseModel):
    section: str
    kind: str
    rate: float
    effective_from: date | None = None
    source: str = "scraper"
