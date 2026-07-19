"""Normalized schema for the Tax Deduction Certificate module.

Design notes
------------
* ``Transaction`` preserves **all 21 source columns exactly as named** via the
  ``SOURCE_COLUMNS`` mapping used by the import service; DB columns use
  snake_case but the original header is kept in ``column_map`` metadata and
  round-trips on export.
* ``Supplier`` is deduplicated on TIN and carries ``BIN`` as a first-class,
  manually editable field (absent from the sheet).
* ``SupplierContact`` allows multiple emails / WhatsApp numbers per supplier.
* Certificates snapshot their lines at generation time so later imports don't
  silently rewrite an issued document. ``remarks`` and ``has_12_digit_tin``
  are the only mutable fields.
"""
import enum
from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class PartyType(str, enum.Enum):
    SUPPLIER = "supplier"
    EMPLOYEE = "employee"
    OTHER = "other"


class Company(Base):
    """A legal entity issuing certificates. Owns identity, seal, letterhead,
    numbering, and named signatures — everything except SMTP/WhatsApp
    transport config, which stays global on OrgSettings."""

    __tablename__ = "tds_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    address: Mapped[str | None] = mapped_column(Text)
    seal_path: Mapped[str | None] = mapped_column(String(512))  # PNG w/ alpha
    letterhead_header_path: Mapped[str | None] = mapped_column(String(512))
    letterhead_footer_path: Mapped[str | None] = mapped_column(String(512))
    officer_name: Mapped[str | None] = mapped_column(String(255))
    officer_designation: Mapped[str | None] = mapped_column(String(255))
    officer_email: Mapped[str | None] = mapped_column(String(255))
    default_bank_name: Mapped[str | None] = mapped_column(String(255))
    default_description: Mapped[str | None] = mapped_column(
        String(255), default="Supply of Goods"
    )
    # The company auto-selected in the UI / used to backfill pre-existing data.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    signatures: Mapped[list["Signature"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Signature(Base):
    """A named signatory's signature, scoped to a company. Every signature
    flagged ``enabled`` renders on every certificate generated for that
    company, side by side in the signature row (no per-certificate choice)."""

    __tablename__ = "tds_signatures"
    __table_args__ = (UniqueConstraint("company_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("tds_companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))  # signatory's name
    designation: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    image_path: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    company: Mapped[Company] = relationship(back_populates="signatures")


class Supplier(Base):
    __tablename__ = "tds_suppliers"
    __table_args__ = (UniqueConstraint("company_id", "tin", name="uq_supplier_company_tin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("tds_companies.id"), index=True)
    tin: Mapped[str] = mapped_column(String(20), index=True)
    # BIN is not present in the source sheet; first-class + manually editable.
    bin: Mapped[str | None] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    # Certificates are generated for suppliers/vendors only; enforced in the
    # generation service by checking this flag.
    party_type: Mapped[PartyType] = mapped_column(
        Enum(PartyType), default=PartyType.SUPPLIER
    )
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    contacts: Mapped[list["SupplierContact"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="supplier")


class ContactKind(str, enum.Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class SupplierContact(Base):
    """Multiple email addresses and WhatsApp numbers per supplier."""

    __tablename__ = "tds_supplier_contacts"
    __table_args__ = (UniqueConstraint("supplier_id", "kind", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("tds_suppliers.id"))
    kind: Mapped[ContactKind] = mapped_column(Enum(ContactKind))
    value: Mapped[str] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    supplier: Mapped[Supplier] = relationship(back_populates="contacts")


class ImportBatch(Base):
    __tablename__ = "tds_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("tds_companies.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default="depot")  # depot | challan
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    ok_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    errors: Mapped[list["ImportRowError"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportRowError(Base):
    """Row-level validation errors surfaced in the Import screen."""

    __tablename__ = "tds_import_row_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("tds_import_batches.id"))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based Excel row
    column: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    raw_row: Mapped[str | None] = mapped_column(Text)  # JSON dump of the row

    batch: Mapped[ImportBatch] = relationship(back_populates="errors")


class Transaction(Base):
    """One row of the Depot-SCB sheet. All 21 source columns preserved."""

    __tablename__ = "tds_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("tds_companies.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("tds_import_batches.id"))
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("tds_suppliers.id"), index=True
    )

    category: Mapped[str | None] = mapped_column(String(64))
    cheque_date: Mapped[date | None] = mapped_column(Date, index=True)
    cheque_number: Mapped[str | None] = mapped_column(String(64))
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    supplier_address: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(String(255))
    whatsapp_no: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    depot_code: Mapped[str | None] = mapped_column(String(64))
    description_of_payment: Mapped[str | None] = mapped_column(String(255))
    sum_of_bill_amount: Mapped[float | None] = mapped_column(Float)
    sum_of_tds: Mapped[float | None] = mapped_column(Float)
    # Legacy column — no longer populated by import/challan upload (VDS is
    # excluded from the pipeline); kept only so old rows keep their data.
    sum_of_vds: Mapped[float | None] = mapped_column(Float)
    match: Mapped[str | None] = mapped_column(String(64))
    section: Mapped[str | None] = mapped_column(String(32), index=True)
    tin: Mapped[str | None] = mapped_column(String(20), index=True)
    challan_no: Mapped[str | None] = mapped_column(String(64), index=True)
    challan_date: Mapped[date | None] = mapped_column(Date)
    cheque_challan_sl: Mapped[str | None] = mapped_column(String(32))
    month: Mapped[str | None] = mapped_column(String(32), index=True)
    total_challan_amount: Mapped[float | None] = mapped_column(Float)
    remarks: Mapped[str | None] = mapped_column(Text)

    # Derived: Bangladeshi fiscal year (Jul-Jun), e.g. "2025-26". This is the
    # `period` half of the (TIN, period) certificate grouping key.
    fiscal_year: Mapped[str | None] = mapped_column(String(9), index=True)

    supplier: Mapped[Supplier | None] = relationship(back_populates="transactions")


class CertStatus(str, enum.Enum):
    PENDING = "pending"       # grouping exists, certificate not generated yet
    GENERATED = "generated"
    SENT = "sent"
    VOID = "void"


class Certificate(Base):
    __tablename__ = "tds_certificates"
    __table_args__ = (
        UniqueConstraint("company_id", "tin", "period", name="uq_cert_company_tin_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("tds_companies.id"), index=True)
    certificate_no: Mapped[str | None] = mapped_column(String(64), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("tds_suppliers.id"))
    tin: Mapped[str] = mapped_column(String(20), index=True)
    period: Mapped[str] = mapped_column(String(9), index=True)  # fiscal year
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    total_payment: Mapped[float] = mapped_column(Float, default=0)
    total_tax_deducted: Mapped[float] = mapped_column(Float, default=0)
    total_vds: Mapped[float] = mapped_column(Float, default=0)
    amount_in_words: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)  # editable field
    # Row 3 "12-digit TIN?" Yes/No — defaults from tin length at generation
    # time, but the officer can override it (e.g. TIN typos, format edge cases).
    has_12_digit_tin: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[CertStatus] = mapped_column(Enum(CertStatus), default=CertStatus.GENERATED)
    issue_date: Mapped[date] = mapped_column(Date, default=date.today)
    # "auto" re-applies today's date whenever the certificate is (re)saved;
    # "manual" keeps whatever issue_date was explicitly set in the preview.
    issue_date_mode: Mapped[str] = mapped_column(String(10), default="auto")
    pdf_path: Mapped[str | None] = mapped_column(String(512))
    # High-resolution JPEG rasterized directly from pdf_path (same source,
    # so it's pixel-identical to the PDF) — the share-ready artifact for
    # WhatsApp/email, sized to avoid WhatsApp's own re-compression.
    image_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    company: Mapped[Company] = relationship()
    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["CertificateLine"]] = relationship(
        back_populates="certificate", cascade="all, delete-orphan",
        order_by="CertificateLine.sl",
    )
    challan_lines: Mapped[list["CertificateChallanLine"]] = relationship(
        back_populates="certificate", cascade="all, delete-orphan",
        order_by="CertificateChallanLine.sl",
    )


class CertificateLine(Base):
    """Section 06 rows — Particulars of payment and tax deduction."""

    __tablename__ = "tds_certificate_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("tds_certificates.id"))
    sl: Mapped[int] = mapped_column(Integer)
    date_of_payment: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(255))
    section: Mapped[str | None] = mapped_column(String(32))
    amount_of_payment: Mapped[float | None] = mapped_column(Float)
    amount_of_tax_deducted: Mapped[float | None] = mapped_column(Float)
    remarks: Mapped[str | None] = mapped_column(Text)

    certificate: Mapped[Certificate] = relationship(back_populates="lines")


class CertificateChallanLine(Base):
    """Section 07 rows — Payment of deducted tax to the credit of the Govt."""

    __tablename__ = "tds_certificate_challan_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("tds_certificates.id"))
    sl: Mapped[int] = mapped_column(Integer)
    challan_number: Mapped[str | None] = mapped_column(String(64))
    challan_date: Mapped[date | None] = mapped_column(Date)
    bank_name: Mapped[str | None] = mapped_column(String(255))
    total_challan_amount: Mapped[float | None] = mapped_column(Float)
    amount_related: Mapped[float | None] = mapped_column(Float)
    remarks: Mapped[str | None] = mapped_column(Text)

    certificate: Mapped[Certificate] = relationship(back_populates="challan_lines")


class OrgSettings(Base):
    """Single-row organizational settings (id=1)."""

    __tablename__ = "tds_org_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    company_name: Mapped[str | None] = mapped_column(String(255))
    company_address: Mapped[str | None] = mapped_column(Text)
    logo_path: Mapped[str | None] = mapped_column(String(512))
    seal_signature_path: Mapped[str | None] = mapped_column(String(512))  # legacy combined PNG w/ alpha
    signature_path: Mapped[str | None] = mapped_column(String(512))  # PNG w/ alpha, preferred over the legacy combined field
    seal_path: Mapped[str | None] = mapped_column(String(512))  # PNG w/ alpha, preferred over the legacy combined field
    officer_name: Mapped[str | None] = mapped_column(String(255))
    officer_designation: Mapped[str | None] = mapped_column(String(255))
    officer_email: Mapped[str | None] = mapped_column(String(255))
    default_bank_name: Mapped[str | None] = mapped_column(String(255))
    default_description: Mapped[str | None] = mapped_column(
        String(255), default="Supply of Goods"
    )

    # SMTP — supports Microsoft 365, Google Workspace, Zimbra, or any SMTP host.
    smtp_host: Mapped[str | None] = mapped_column(String(255))
    smtp_port: Mapped[int | None] = mapped_column(Integer, default=587)
    smtp_user: Mapped[str | None] = mapped_column(String(255))
    smtp_password: Mapped[str | None] = mapped_column(String(255))
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    smtp_from: Mapped[str | None] = mapped_column(String(255))

    # WhatsApp — provider is "cloud" (WhatsApp Business Cloud API) or "twilio".
    wa_provider: Mapped[str | None] = mapped_column(String(20), default="cloud")
    wa_token: Mapped[str | None] = mapped_column(String(512))
    wa_phone_number_id: Mapped[str | None] = mapped_column(String(64))
    wa_twilio_sid: Mapped[str | None] = mapped_column(String(64))
    wa_twilio_auth: Mapped[str | None] = mapped_column(String(128))
    wa_twilio_from: Mapped[str | None] = mapped_column(String(32))

    # Dispatch mode: "online" sends immediately; "offline" only queues.
    dispatch_mode: Mapped[str] = mapped_column(String(10), default="online")


class NumberingConfig(Base):
    """Admin-configurable certificate numbering. One row per company."""

    __tablename__ = "tds_numbering_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("tds_companies.id"), unique=True, index=True
    )
    # Free-text token substituted for {CompanyName} — decoupled from
    # Company.name so the admin can keep a short form (e.g. "Renata PLC").
    company_token: Mapped[str] = mapped_column(String(64), default="COMPANY")
    fiscal_year_format: Mapped[str] = mapped_column(String(16), default="YYYY-YY")
    pad_width: Mapped[int] = mapped_column(Integer, default=1)
    start_number: Mapped[int] = mapped_column(Integer, default=1)
    reset_policy: Mapped[str] = mapped_column(String(16), default="per_fiscal_year")
    separator: Mapped[str] = mapped_column(String(4), default="/")
    # Admin-editable token template. Supported tokens: {CompanyName}, {FiscalYear},
    # {AutoNumber}, {sep} (substituted with `separator`). Default reproduces the
    # historical hardcoded "{company}{sep}{fy}{sep}{number}" format exactly.
    number_format: Mapped[str] = mapped_column(
        String(128), default="{CompanyName}{sep}{FiscalYear}{sep}{AutoNumber}"
    )


class NumberSequence(Base):
    """Sequential allocator. One row per scope ("2025-26" or "global").

    Allocation uses SELECT ... FOR UPDATE (row lock) so concurrent
    generations can never receive the same number. See NumberingService.
    """

    __tablename__ = "tds_number_sequences"

    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)


class DispatchChannel(str, enum.Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class DispatchStatus(str, enum.Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class DispatchJob(Base):
    """Email/WhatsApp dispatch queue — supports online + offline modes."""

    __tablename__ = "tds_dispatch_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("tds_certificates.id"))
    channel: Mapped[DispatchChannel] = mapped_column(Enum(DispatchChannel))
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[DispatchStatus] = mapped_column(
        Enum(DispatchStatus), default=DispatchStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Set when the email's tracking image is fetched by the recipient's client.
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)

    certificate: Mapped[Certificate] = relationship()


class TaxRate(Base):
    """Section -> expected TDS/VDS/VAT rates. Updated by the rate-scraper hook."""

    __tablename__ = "tds_tax_rates"
    __table_args__ = (UniqueConstraint("section", "kind", "effective_from"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # tds | vds | vat
    rate: Mapped[float] = mapped_column(Float)  # e.g. 0.05 for 5%
    effective_from: Mapped[date] = mapped_column(Date, default=date.today)
    source: Mapped[str | None] = mapped_column(String(64))  # "scraper" | "manual"
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class RateAnomaly(Base):
    """Anomalies raised by the rate update hook (scrape failure, big jumps...)."""

    __tablename__ = "tds_rate_anomalies"

    id: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str | None] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class OverrideLog(Base):
    """Logged reasons when a user overrides pre-dispatch anomaly blocks."""

    __tablename__ = "tds_override_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("tds_certificates.id"))
    anomalies: Mapped[str] = mapped_column(Text)  # JSON list of overridden codes
    reason: Mapped[str] = mapped_column(Text)
    user: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
