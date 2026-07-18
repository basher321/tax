"""Excel import service for the Depot-SCB sheet and challan files.

Parses the workbook directly with openpyxl/pandas — no Excel formula
evaluation happens at runtime. Row-level validation errors are recorded
(never aborting the whole import for one bad row).
"""
import json
import re
from datetime import date, datetime

import pandas as pd
from sqlalchemy.orm import Session

from ..models.entities import (
    ContactKind,
    ImportBatch,
    ImportRowError,
    Supplier,
    SupplierContact,
    Transaction,
)

# The 21 source columns, exactly as named in the sheet, mapped to DB fields.
# ("Challan No" appears without a trailing dot in the file; we accept both.)
SOURCE_COLUMNS = {
    "Category": "category",
    "Cheque Date": "cheque_date",
    "Cheque Number": "cheque_number",
    "Supplier Name": "supplier_name",
    "Supplier Address": "supplier_address",
    "Bank Name": "bank_name",
    "WhatsApp No.": "whatsapp_no",
    "Email": "email",
    "Depot Code": "depot_code",
    "Description of Payment": "description_of_payment",
    "Sum of Bill Amount": "sum_of_bill_amount",
    "Sum of TDS": "sum_of_tds",
    # Sum of VDS is intentionally excluded from import/field mapping/storage.
    # Base Amount / TDS Rate are optional: when both are present, TDS is
    # computed as Base Amount x TDS Rate instead of taken literally.
    "Base Amount": "_base_amount",
    "TDS Rate": "_tds_rate",
    "Match": "match",
    "Section": "section",
    "TIN": "tin",
    "Challan No": "challan_no",
    "Challan No.": "challan_no",
    "Challan Date": "challan_date",
    "Cheque/Challan SL": "cheque_challan_sl",
    "Month": "month",
    "Total Challan Amount": "total_challan_amount",
    "Remarks": "remarks",
}

REQUIRED_FIELDS = ["Supplier Name", "TIN", "Sum of TDS", "Month", "Section"]
TIN_RE = re.compile(r"^\d{10,13}$")  # 12-digit standard; tolerate 10-13 legacy

MONTH_RE = re.compile(r"^([A-Za-z]+)'(\d{2})$")
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


def parse_month_label(label: str) -> date | None:
    """'December'25' -> date(2025, 12, 1)."""
    if not label:
        return None
    m = MONTH_RE.match(str(label).strip())
    if not m:
        return None
    name, yy = m.groups()
    mo = _MONTHS.get(name.lower())
    if not mo:
        return None
    return date(2000 + int(yy), mo, 1)


def fiscal_year_for(d: date) -> str:
    """Bangladeshi fiscal year (Jul 1 – Jun 30), e.g. 2025-12 -> '2025-26'."""
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _parse_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(value) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        f = float(value)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def _find_header_row(path: str, sheet_name: str) -> int | None:
    """Read the sheet locating the header row that contains 'Category'."""
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
    for i in range(min(10, len(raw))):
        if "Category" in [str(v).strip() for v in raw.iloc[i].tolist()]:
            return i
    return None


def load_depot_sheet(path: str, sheet_name: str = "Depot-SCB") -> pd.DataFrame:
    """Read the Depot sheet, locating the header row that contains 'Category'."""
    with pd.ExcelFile(path) as xl:
        sheet_names = xl.sheet_names
    candidates = [sheet_name] if sheet_name in sheet_names else []
    candidates.extend([name for name in sheet_names if name not in candidates])

    selected_sheet = None
    header_idx = None
    for candidate in candidates:
        header_idx = _find_header_row(path, candidate)
        if header_idx is not None:
            selected_sheet = candidate
            break

    if header_idx is None:
        raise ValueError("Could not find header row containing 'Category'")
    df = pd.read_excel(path, sheet_name=selected_sheet, header=header_idx, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    df["__excel_row"] = df.index + header_idx + 2  # 1-based Excel row numbers
    return df


def _get_or_create_supplier(db: Session, company_id: int, tin: str, name: str,
                            address, email, wa) -> Supplier:
    sup = (
        db.query(Supplier)
        .filter(Supplier.company_id == company_id, Supplier.tin == tin)
        .first()
    )
    if not sup:
        sup = Supplier(company_id=company_id, tin=tin, name=name, address=address)
        db.add(sup)
        db.flush()
    else:
        # Keep the most recent non-empty name/address.
        if name:
            sup.name = name
        if address:
            sup.address = address
    for kind, value in ((ContactKind.EMAIL, email), (ContactKind.WHATSAPP, wa)):
        if value:
            exists = any(c.kind == kind and c.value == value for c in sup.contacts)
            if not exists:
                sup.contacts.append(SupplierContact(kind=kind, value=value))
                db.flush()
    return sup


def import_depot_workbook(db: Session, path: str, filename: str, company_id: int) -> ImportBatch:
    """Import the Depot-SCB sheet: validate row by row, persist good rows,
    record errors for bad ones. Never aborts on a single bad row."""
    df = load_depot_sheet(path)
    batch = ImportBatch(company_id=company_id, filename=filename, kind="depot", total_rows=len(df))
    db.add(batch)
    db.flush()

    ok = err = 0
    for _, row in df.iterrows():
        excel_row = int(row["__excel_row"])
        row_errors: list[tuple[str | None, str]] = []

        def val(col):
            return row.get(col)

        # --- required fields ---
        has_base_rate = (
            _parse_number(val("Base Amount")) is not None
            and _parse_number(val("TDS Rate")) is not None
        )
        for col in REQUIRED_FIELDS:
            if col == "Sum of TDS" and has_base_rate:
                continue  # TDS will be computed from Base Amount x TDS Rate instead
            if _clean(val(col)) is None and _parse_number(val(col)) is None:
                row_errors.append((col, f"Required field '{col}' is missing"))

        # --- TIN format ---
        tin = _clean(val("TIN"))
        if tin is not None:
            tin = re.sub(r"\D", "", tin)
            if not TIN_RE.match(tin):
                row_errors.append(("TIN", f"TIN '{tin}' is not a valid 12-digit TIN"))

        # --- numeric fields ---
        numbers = {}
        for col in ("Sum of Bill Amount", "Sum of TDS", "Total Challan Amount",
                    "Base Amount", "TDS Rate"):
            v = val(col)
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                n = _parse_number(v)
                if n is None:
                    row_errors.append((col, f"'{v}' is not a number"))
                numbers[col] = n
            else:
                numbers[col] = None

        # Base Amount x TDS Rate overrides the literal Sum of TDS column when
        # both are present and parse as numbers; otherwise Sum of TDS (already
        # based on Sum of Bill Amount upstream in the sheet) is used as-is.
        if numbers["Base Amount"] is not None and numbers["TDS Rate"] is not None:
            computed_tds = round(numbers["Base Amount"] * numbers["TDS Rate"], 2)
        else:
            computed_tds = numbers["Sum of TDS"]

        # --- dates ---
        cheque_date = _parse_date(val("Cheque Date"))
        if _clean(val("Cheque Date")) and cheque_date is None:
            row_errors.append(("Cheque Date", f"Unparseable date '{val('Cheque Date')}'"))
        challan_date = _parse_date(val("Challan Date"))
        if _clean(val("Challan Date")) and challan_date is None:
            row_errors.append(("Challan Date", f"Unparseable date '{val('Challan Date')}'"))

        month_label = _clean(val("Month"))
        month_date = parse_month_label(month_label) if month_label else None
        if month_label and month_date is None:
            row_errors.append(("Month", f"Unparseable month label '{month_label}'"))

        if row_errors:
            err += 1
            for col, msg in row_errors:
                db.add(ImportRowError(
                    batch_id=batch.id, row_number=excel_row, column=col,
                    message=msg,
                    raw_row=json.dumps(
                        {k: str(v) for k, v in row.items() if k != "__excel_row"},
                        default=str)[:4000],
                ))
            continue

        supplier = _get_or_create_supplier(
            db, company_id, tin, _clean(val("Supplier Name")),
            _clean(val("Supplier Address")), _clean(val("Email")),
            _clean(val("WhatsApp No.")),
        )

        basis = month_date or cheque_date
        txn = Transaction(
            company_id=company_id,
            batch_id=batch.id,
            supplier_id=supplier.id,
            category=_clean(val("Category")),
            cheque_date=cheque_date,
            cheque_number=_clean(val("Cheque Number")),
            supplier_name=_clean(val("Supplier Name")),
            supplier_address=_clean(val("Supplier Address")),
            bank_name=_clean(val("Bank Name")),
            whatsapp_no=_clean(val("WhatsApp No.")),
            email=_clean(val("Email")),
            depot_code=_clean(val("Depot Code")),
            description_of_payment=_clean(val("Description of Payment")),
            sum_of_bill_amount=numbers["Sum of Bill Amount"],
            sum_of_tds=computed_tds,
            match=_clean(val("Match")),
            section=_clean(val("Section")),
            tin=tin,
            challan_no=_clean(val("Challan No") if "Challan No" in df.columns
                              else val("Challan No.")),
            challan_date=challan_date,
            cheque_challan_sl=_clean(val("Cheque/Challan SL")),
            month=month_label,
            total_challan_amount=numbers["Total Challan Amount"],
            remarks=_clean(val("Remarks")),
            fiscal_year=fiscal_year_for(basis) if basis else None,
        )
        db.add(txn)
        ok += 1

    batch.ok_rows = ok
    batch.error_rows = err
    db.commit()
    return batch


def import_challan_file(db: Session, path: str, filename: str,
                        company_id: int) -> tuple[ImportBatch, list[int]]:
    """Challan upload: auto-populate Challan No/Date/Total Challan Amount/Section
    and the adjusted Sum of Bill Amount/TDS on matching (TIN or supplier name,
    Month) transaction records, scoped to the given company. VDS is never
    auto-populated. Manual override afterward happens via
    PATCH /api/transactions/{id}.

    Expected columns (flexible header row): TIN and/or Supplier Name, Month,
    Challan No, Challan Date, Total Challan Amount, Section, and optionally
    Sum of Bill Amount / Sum of TDS (same headers as Depot-SCB).

    Returns (batch, updated_transaction_ids) so the route can surface exactly
    which rows changed for review/manual override.
    """
    raw = pd.read_excel(path, header=None, dtype=object)
    header_idx = 0
    for i in range(min(10, len(raw))):
        cells = [str(v).strip() for v in raw.iloc[i].tolist()]
        if any(c in cells for c in ("Challan No", "Challan No.", "Challan Number")):
            header_idx = i
            break
    df = pd.read_excel(path, header=header_idx, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]

    def col(*names):
        for n in names:
            if n in df.columns:
                return n
        return None

    c_tin = col("TIN")
    c_name = col("Supplier Name")
    c_month = col("Month")
    c_no = col("Challan No", "Challan No.", "Challan Number")
    c_date = col("Challan Date", "Challan date")
    c_amt = col("Total Challan Amount", "Total amount in the challan")
    c_sec = col("Section")
    c_bill = col("Sum of Bill Amount")
    c_tds = col("Sum of TDS")

    batch = ImportBatch(company_id=company_id, filename=filename, kind="challan", total_rows=len(df))
    db.add(batch)
    db.flush()

    ok = err = 0
    updated_ids: list[int] = []
    for idx, row in df.iterrows():
        excel_row = idx + header_idx + 2
        challan_no = _clean(row.get(c_no)) if c_no else None
        if not challan_no:
            err += 1
            db.add(ImportRowError(batch_id=batch.id, row_number=excel_row,
                                  column=c_no, message="Missing challan number"))
            continue

        q = db.query(Transaction).filter(Transaction.company_id == company_id)
        tin = re.sub(r"\D", "", _clean(row.get(c_tin)) or "") if c_tin else ""
        name = _clean(row.get(c_name)) if c_name else None
        month = _clean(row.get(c_month)) if c_month else None
        if tin:
            q = q.filter(Transaction.tin == tin)
        elif name:
            q = q.filter(Transaction.supplier_name == name)
        else:
            err += 1
            db.add(ImportRowError(batch_id=batch.id, row_number=excel_row,
                                  message="Row has neither TIN nor Supplier Name"))
            continue
        if month:
            q = q.filter(Transaction.month == month)

        matches = q.all()
        if not matches:
            err += 1
            db.add(ImportRowError(
                batch_id=batch.id, row_number=excel_row,
                message=f"No transaction matches TIN/name + month for challan {challan_no}"))
            continue

        ch_date = _parse_date(row.get(c_date)) if c_date else None
        ch_amt = _parse_number(row.get(c_amt)) if c_amt else None
        ch_sec = _clean(row.get(c_sec)) if c_sec else None
        ch_bill = _parse_number(row.get(c_bill)) if c_bill else None
        ch_tds = _parse_number(row.get(c_tds)) if c_tds else None
        for t in matches:
            t.challan_no = challan_no
            if ch_date:
                t.challan_date = ch_date
            if ch_amt is not None:
                t.total_challan_amount = ch_amt
            if ch_sec:
                t.section = ch_sec
            if ch_bill is not None:
                t.sum_of_bill_amount = ch_bill
            if ch_tds is not None:
                t.sum_of_tds = ch_tds
            updated_ids.append(t.id)
        ok += 1

    batch.ok_rows = ok
    batch.error_rows = err
    db.commit()
    return batch, updated_ids
