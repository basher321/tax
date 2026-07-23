"""Replicates the Certificate sheet's INDEX/FILTER/SUM mapping in Python.

The workbook's Certificate sheet uses array formulas of the shape

    =IFERROR(INDEX(FILTER(<Depot columns>, Challan!$C:$C = $TIN), Sl), "")
    =SUM(E14:E34)   / =SUM(F14:F34)   / =SUM(F53:F73)

i.e. it filters Depot-SCB rows for one TIN, lays them out in order as the
Section 06 payment-particular lines, mirrors challan info into Section 07,
and totals the payment / tax-deducted columns. This module reimplements that
data flow: Depot-SCB rows -> group by (TIN, period) -> ordered line items +
SUM totals — with no Excel evaluation at runtime.
"""
from dataclasses import dataclass, field
from datetime import date
from calendar import monthrange

from sqlalchemy.orm import Session

from ..models.entities import Transaction
from .excel_import import parse_month_label


@dataclass
class PaymentLine:                      # Section 06 row
    sl: int
    date_of_payment: date | None
    description: str | None
    section: str | None
    amount_of_payment: float | None
    amount_of_tax_deducted: float | None
    remarks: str | None = None
    transaction_id: int | None = None   # source row, for edit-propagation


@dataclass
class ChallanLine:                      # Section 07 row
    sl: int
    challan_number: str | None
    challan_date: date | None
    bank_name: str | None
    total_challan_amount: float | None
    amount_related: float | None
    remarks: str | None = None
    transaction_id: int | None = None   # source row, for edit-propagation


@dataclass
class CertificateData:
    tin: str
    period: str                          # fiscal year e.g. "2025-26"
    supplier_id: int | None
    supplier_name: str | None
    supplier_address: str | None
    period_from: date | None
    period_to: date | None
    lines: list[PaymentLine] = field(default_factory=list)
    challan_lines: list[ChallanLine] = field(default_factory=list)
    total_payment: float = 0.0           # = SUM(E14:E34)
    total_tax_deducted: float = 0.0      # = SUM(F14:F34)
    total_vds: float = 0.0
    total_challan_related: float = 0.0   # = SUM(F53:F73)


def build_certificate_data(
    db: Session,
    company_id: int,
    tin: str,
    period: str,
    default_description: str = "Supply of Goods",
    default_bank: str | None = None,
) -> CertificateData | None:
    """Aggregate all Depot-SCB rows for one (company, TIN, fiscal-year) group."""
    txns: list[Transaction] = (
        db.query(Transaction)
        .filter(Transaction.company_id == company_id, Transaction.tin == tin,
                Transaction.fiscal_year == period)
        .order_by(Transaction.cheque_date, Transaction.id)   # group/order by date
        .all()
    )
    if not txns:
        return None

    first = txns[0]
    # Period display: fiscal-year start -> end of the latest covered month,
    # matching the template ("From 1 Jul'25 to 31 Dec'25").
    fy_start_year = int(period.split("-")[0])
    period_from = date(fy_start_year, 7, 1)
    month_dates = [d for d in (parse_month_label(t.month) for t in txns) if d]
    if month_dates:
        last = max(month_dates)
        period_to = date(last.year, last.month, monthrange(last.year, last.month)[1])
    else:
        period_to = max((t.cheque_date for t in txns if t.cheque_date),
                        default=date(fy_start_year + 1, 6, 30))

    data = CertificateData(
        tin=tin, period=period,
        supplier_id=first.supplier_id,
        supplier_name=first.supplier_name,
        supplier_address=first.supplier_address,
        period_from=period_from, period_to=period_to,
    )

    for i, t in enumerate(txns, start=1):
        # Section 06 — one line per source row (INDEX(FILTER(...), Sl)).
        data.lines.append(PaymentLine(
            sl=i,
            date_of_payment=t.cheque_date,
            description=t.description_of_payment or default_description,
            section=t.section,
            amount_of_payment=t.sum_of_bill_amount,
            amount_of_tax_deducted=t.sum_of_tds,
            transaction_id=t.id,
        ))
        # Section 07 — challan credit for the same row; "Amount relating to
        # this certificate" is the row's TDS (this is what makes the Section
        # 07 total equal the Section 06 tax total, as in the template).
        data.challan_lines.append(ChallanLine(
            sl=i,
            challan_number=t.challan_no,
            challan_date=t.challan_date,
            bank_name=t.bank_name or default_bank,
            total_challan_amount=t.total_challan_amount,
            amount_related=t.sum_of_tds,
            transaction_id=t.id,
        ))
        data.total_payment += t.sum_of_bill_amount or 0.0
        data.total_tax_deducted += t.sum_of_tds or 0.0
        data.total_vds += t.sum_of_vds or 0.0
        data.total_challan_related += t.sum_of_tds or 0.0

    # Round like the sheet displays.
    data.total_payment = round(data.total_payment, 2)
    data.total_tax_deducted = round(data.total_tax_deducted, 2)
    data.total_vds = round(data.total_vds, 2)
    data.total_challan_related = round(data.total_challan_related, 2)
    return data


def list_groupings(
    db: Session,
    company_id: int | None = None,
    tin: str | None = None,
    bin: str | None = None,
    supplier_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """All distinct (TIN, period) groupings present in imported data, scoped
    to one company — or across all companies when company_id is None (used
    only by the Dashboard's global overview). Filters mirror GET
    /certificates so the Pending and Generated tables search identically."""
    from sqlalchemy import func

    from ..models.entities import Supplier

    q = (
        db.query(
            Transaction.tin,
            Transaction.fiscal_year,
            func.max(Transaction.supplier_name),
            func.max(Supplier.bin),
            func.count(Transaction.id),
            func.sum(Transaction.sum_of_bill_amount),
            func.sum(Transaction.sum_of_tds),
            func.min(Transaction.cheque_date),
            func.max(Transaction.cheque_date),
        )
        .outerjoin(Supplier, Transaction.supplier_id == Supplier.id)
        .filter(Transaction.tin.isnot(None), Transaction.fiscal_year.isnot(None))
    )
    if company_id is not None:
        q = q.filter(Transaction.company_id == company_id)
    if tin:
        q = q.filter(Transaction.tin.like(f"%{tin}%"))
    if bin:
        q = q.filter(Supplier.bin.like(f"%{bin}%"))
    if supplier_name:
        q = q.filter(Transaction.supplier_name.ilike(f"%{supplier_name}%"))
    if date_from:
        q = q.filter(Transaction.cheque_date >= date_from)
    if date_to:
        q = q.filter(Transaction.cheque_date <= date_to)
    rows = q.group_by(Transaction.tin, Transaction.fiscal_year).all()
    return [
        {
            "tin": r[0], "period": r[1], "supplier_name": r[2],
            "bin": r[3],
            "row_count": r[4],
            "total_payment": round(r[5] or 0, 2),
            "total_tax_deducted": round(r[6] or 0, 2),
            "payment_from": r[7],
            "payment_to": r[8],
        }
        for r in rows
    ]
