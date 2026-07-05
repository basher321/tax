"""Auto certificate numbering: {CompanyName}/{FiscalYear}/{AutoNumber}.

Uniqueness and sequential allocation under concurrency is guaranteed by a
row-level lock on the tds_number_sequences row (SELECT ... FOR UPDATE on
PostgreSQL). On SQLite the database-level write lock serializes writers, so
the same code path remains correct in development.
"""
from sqlalchemy.orm import Session

from ..models.entities import NumberingConfig, NumberSequence


def get_numbering_config(db: Session) -> NumberingConfig:
    cfg = db.get(NumberingConfig, 1)
    if not cfg:
        cfg = NumberingConfig(id=1)
        db.add(cfg)
        db.flush()
    return cfg


def _format_fiscal_year(period: str, fmt: str) -> str:
    """period is stored as '2025-26'. Supported formats: YYYY-YY, YYYY, YY-YY."""
    start, end2 = period.split("-")
    if fmt == "YYYY":
        return start
    if fmt == "YY-YY":
        return f"{start[-2:]}-{end2}"
    return f"{start}-{end2}"  # default YYYY-YY


def allocate_certificate_number(db: Session, period: str) -> str:
    """Allocate the next number atomically.

    Implementation: idempotent seed insert (ON CONFLICT DO NOTHING) followed
    by a single atomic ``UPDATE ... SET last_value = last_value + 1
    RETURNING last_value``. The UPDATE takes a row-level lock on PostgreSQL
    and the database write lock on SQLite, so concurrent allocators are
    serialized and can never receive the same number on either backend.
    """
    from sqlalchemy import text

    cfg = get_numbering_config(db)
    scope = period if cfg.reset_policy == "per_fiscal_year" else "global"

    db.execute(
        text(
            "INSERT INTO tds_number_sequences (scope, last_value) "
            "VALUES (:scope, :seed) ON CONFLICT (scope) DO NOTHING"
        ),
        {"scope": scope, "seed": cfg.start_number - 1},
    )
    value = db.execute(
        text(
            "UPDATE tds_number_sequences SET last_value = last_value + 1 "
            "WHERE scope = :scope RETURNING last_value"
        ),
        {"scope": scope},
    ).scalar_one()

    number = str(value).zfill(cfg.pad_width)
    fy = _format_fiscal_year(period, cfg.fiscal_year_format)
    return f"{cfg.company_token}{cfg.separator}{fy}{cfg.separator}{number}"
