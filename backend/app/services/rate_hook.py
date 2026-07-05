"""Rate Update Hook.

Service interface the existing rate-scraper automation calls to push
TDS/VDS/VAT rate updates. New rates apply to certificate calculations going
forward (validation.check_certificate always reads the latest effective
rate). Anomalies (big jumps, scrape failures, missing rates) are recorded as
RateAnomaly rows and surfaced in the API/UI.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from ..models.entities import RateAnomaly, TaxRate, Transaction

# A change of more than 50% relative to the previous rate is suspicious.
MAX_RELATIVE_JUMP = 0.5


@dataclass
class RateUpdate:
    section: str
    kind: str          # "tds" | "vds" | "vat"
    rate: float        # fraction, e.g. 0.05
    effective_from: date | None = None
    source: str = "scraper"


def apply_rate_updates(db: Session, updates: list[RateUpdate]) -> dict:
    applied, anomalies = 0, []

    for u in updates:
        if u.kind not in ("tds", "vds", "vat"):
            anomalies.append(_anomaly(db, u.section, u.kind,
                                      f"Unknown rate kind '{u.kind}'"))
            continue
        if u.rate < 0 or u.rate > 1:
            anomalies.append(_anomaly(db, u.section, u.kind,
                                      f"Rate {u.rate} outside [0, 1]"))
            continue

        prev = (
            db.query(TaxRate)
            .filter(TaxRate.section == u.section, TaxRate.kind == u.kind)
            .order_by(TaxRate.effective_from.desc())
            .first()
        )
        if prev and prev.rate > 0:
            jump = abs(u.rate - prev.rate) / prev.rate
            if jump > MAX_RELATIVE_JUMP:
                anomalies.append(_anomaly(
                    db, u.section, u.kind,
                    f"Unexpected rate change magnitude: {prev.rate:.2%} -> "
                    f"{u.rate:.2%} ({jump:.0%} jump). Rate applied but flagged."))

        db.add(TaxRate(
            section=u.section, kind=u.kind, rate=u.rate,
            effective_from=u.effective_from or date.today(), source=u.source,
        ))
        applied += 1

    db.commit()
    return {"applied": applied, "anomalies": [a.message for a in anomalies]}


def report_scrape_failure(db: Session, message: str) -> None:
    """The scraper calls this when it cannot obtain rates at all."""
    _anomaly(db, None, None, f"Rate scrape failure: {message}")
    db.commit()


def check_missing_rates(db: Session) -> list[str]:
    """Flag sections present in transactions with no TDS rate on file."""
    sections = {s for (s,) in db.query(Transaction.section).distinct() if s}
    have = {s for (s,) in db.query(TaxRate.section)
            .filter(TaxRate.kind == "tds").distinct()}
    missing = sorted(sections - have)
    for s in missing:
        _anomaly(db, s, "tds", f"No TDS rate on file for section {s}")
    db.commit()
    return missing


def _anomaly(db: Session, section, kind, message) -> RateAnomaly:
    a = RateAnomaly(section=section, kind=kind, message=message)
    db.add(a)
    return a
