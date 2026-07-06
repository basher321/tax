"""Tests: Excel import parsing, aggregation math against a known sample,
concurrent number allocation, anomaly detection, and offline dispatch queue."""
import os
import smtplib
import threading
from datetime import date
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register tables
from app.database import Base
from app.models.entities import (
    Certificate,
    ContactKind,
    DispatchChannel,
    DispatchStatus,
    DispatchJob,
    PartyType,
    Supplier,
    SupplierContact,
    TaxRate,
    Transaction,
)
from app.services import rate_hook
from app.services.aggregation import build_certificate_data
from app.services.amount_in_words import amount_in_words
from app.services.certificate_generator import (
    GenerationError,
    generate_certificate,
    get_org_settings,
)
from app.services.dispatch.queue import DispatchBlocked, enqueue_dispatch, process_queue
from app.services.dispatch.email_sender import send_test_email
from app.services.dispatch.whatsapp_sender import send_certificate_whatsapp
from app.services.excel_import import (
    fiscal_year_for,
    import_depot_workbook,
    parse_month_label,
)
from app.services.numbering import allocate_certificate_number, get_numbering_config
from app.services.validation import check_certificate

HEADERS = [
    "Category", "Cheque Date", "Cheque Number", "Supplier Name",
    "Supplier Address", "Bank Name", "WhatsApp No.", "Email", "Depot Code",
    "Description of Payment", "Sum of Bill Amount", "Sum of TDS", "Sum of VDS",
    "Match", "Section", "TIN", "Challan No", "Challan Date",
    "Cheque/Challan SL", "Month", "Total Challan Amount", "Remarks",
]


@pytest.fixture
def db(tmp_path):
    # File-backed SQLite so the concurrency test can open multiple sessions.
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def sample_xlsx(tmp_path):
    """Known sample: 3 rows for TIN A (Dec'25), 1 bad row, 1 row for TIN B."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Depot-SCB"
    ws.append([None] * len(HEADERS))
    ws.append([None] * len(HEADERS))
    ws.append(HEADERS)

    def row(name, tin, bill, tds, month, cheque=date(2025, 12, 1),
            section="89", challan="2526-001", chdate="15/01/2026",
            total_ch=100000, email=None, wa=None):
        ws.append(["Depot", cheque, "CHQ1", name, None, None, wa, email, None,
                   None, bill, tds, -bill * 0.05 if bill else None, None,
                   section, tin, challan, chdate, 1, month, total_ch, None])

    row("Alpha Traders", "111122223333", 100000, 5000, "December'25")
    row("Alpha Traders", "111122223333", 50000, 2500, "January'26",
        cheque=date(2026, 1, 10))
    row("Alpha Traders", "111122223333", 20000, 1000, "January'26",
        cheque=date(2026, 1, 20))
    row("Beta Supplies", "444455556666", 80000, 4000, "December'25",
        email="beta@example.com", wa="+8801711111111")
    row("Bad Row Ltd", "12AB", 10000, 500, "December'25")  # invalid TIN

    path = tmp_path / "sample.xlsx"
    wb.save(path)
    return str(path)


# ------------------------------------------------------------- Import -------
def test_import_parses_and_validates(db, sample_xlsx):
    batch = import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    assert batch.total_rows == 5
    assert batch.ok_rows == 4
    assert batch.error_rows == 1
    msgs = [e.message for e in batch.errors]
    assert any("not a valid 12-digit TIN" in m for m in msgs)
    # All 21 source fields land on the transaction row.
    t = db.query(Transaction).filter_by(tin="111122223333").first()
    assert t.category == "Depot" and t.section == "89"
    assert t.challan_no == "2526-001" and t.challan_date == date(2026, 1, 15)
    assert t.month == "December'25" and t.fiscal_year == "2025-26"


def test_month_and_fiscal_year_parsing():
    assert parse_month_label("December'25") == date(2025, 12, 1)
    assert fiscal_year_for(date(2025, 12, 5)) == "2025-26"
    assert fiscal_year_for(date(2026, 3, 1)) == "2025-26"
    assert fiscal_year_for(date(2026, 7, 1)) == "2026-27"


# -------------------------------------------------------- Aggregation -------
def test_aggregation_math_known_sample(db, sample_xlsx):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    data = build_certificate_data(db, "111122223333", "2025-26")
    # SUM logic: 100000+50000+20000 payment; 5000+2500+1000 TDS.
    assert data.total_payment == 170000
    assert data.total_tax_deducted == 8500
    assert data.total_challan_related == 8500  # Section 07 total == TDS total
    assert [ln.sl for ln in data.lines] == [1, 2, 3]  # ordered by date
    assert data.period_from == date(2025, 7, 1)
    assert data.period_to == date(2026, 1, 31)  # end of latest covered month


def test_amount_in_words_matches_template_style():
    assert amount_in_words(41382) == \
        "Forty One Thousand Three Hundred Eighty Two Only."


# ------------------------------------------------- Generation rules ---------
def test_supplier_only_enforced_at_service(db, sample_xlsx):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    sup = db.query(Supplier).filter_by(tin="111122223333").first()
    sup.party_type = PartyType.EMPLOYEE
    db.commit()
    with pytest.raises(GenerationError, match="supplier-only"):
        generate_certificate(db, "111122223333", "2025-26")


def test_duplicate_certificate_blocked(db, sample_xlsx):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    generate_certificate(db, "444455556666", "2025-26")
    with pytest.raises(GenerationError, match="already exists"):
        generate_certificate(db, "444455556666", "2025-26")


# --------------------------------------------- Numbering concurrency --------
def test_concurrent_number_allocation(tmp_path):
    url = f"sqlite:///{tmp_path}/conc.db"
    engine = create_engine(url, connect_args={"check_same_thread": False,
                                              "timeout": 30})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    s0 = Session()
    cfg = get_numbering_config(s0)
    cfg.company_token = "ACME"
    cfg.pad_width = 5
    s0.commit()
    s0.close()

    results, errors = [], []

    def worker():
        s = Session()
        try:
            n = allocate_certificate_number(s, "2025-26")
            s.commit()
            results.append(n)
        except Exception as e:  # noqa: BLE001
            s.rollback()
            errors.append(e)
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(results) == 20
    assert len(set(results)) == 20, "numbers must be unique under concurrency"
    suffixes = sorted(int(r.split("/")[-1]) for r in results)
    assert suffixes == list(range(1, 21)), "numbers must be sequential"
    assert results[0].startswith("ACME/2025-26/")


# ---------------------------------------------------- Anomaly checks --------
def test_anomaly_detection_rules(db, sample_xlsx):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    cert = generate_certificate(db, "111122223333", "2025-26")  # no contacts
    org = get_org_settings(db)
    codes = {a.code for a in check_certificate(db, cert, org)}
    assert "MISSING_EMAIL" in codes
    assert "MISSING_WHATSAPP" in codes
    assert "MISSING_SEAL" in codes  # no seal uploaded in this test env

    # TDS reconciliation: expected rate 5%, actual is 5% -> no mismatch...
    db.add(TaxRate(section="89", kind="tds", rate=0.05,
                   effective_from=date(2025, 7, 1)))
    db.commit()
    codes = {a.code for a in check_certificate(db, cert, org)}
    assert "TDS_MISMATCH" not in codes
    # ...but a newer expected rate (10%) makes the 5% deduction anomalous.
    db.add(TaxRate(section="89", kind="tds", rate=0.10,
                   effective_from=date(2026, 6, 1)))
    db.commit()
    codes = {a.code for a in check_certificate(db, cert, org)}
    assert "TDS_MISMATCH" in codes


def test_missing_challan_anomaly(db, sample_xlsx):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    for t in db.query(Transaction).filter_by(tin="444455556666"):
        t.challan_no = None
    db.commit()
    cert = generate_certificate(db, "444455556666", "2025-26")
    org = get_org_settings(db)
    codes = {a.code for a in check_certificate(db, cert, org)}
    assert "MISSING_CHALLAN" in codes


# ------------------------------------------------ Offline dispatch ----------
def test_offline_queue_blocks_then_overrides_then_drains(db, sample_xlsx, monkeypatch):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    cert = generate_certificate(db, "444455556666", "2025-26")
    org = get_org_settings(db)
    org.dispatch_mode = "offline"
    db.commit()

    # Anomalies (missing seal/officer) block dispatch without an override.
    with pytest.raises(DispatchBlocked) as exc:
        enqueue_dispatch(db, cert, DispatchChannel.EMAIL, ["beta@example.com"])
    assert any(a.code == "MISSING_SEAL" for a in exc.value.anomalies)

    # Override with a logged reason -> job queued but NOT sent (offline mode).
    jobs = enqueue_dispatch(db, cert, DispatchChannel.EMAIL,
                            ["beta@example.com"],
                            override_reason="Seal pending, board approved",
                            user="admin")
    assert jobs[0].status == DispatchStatus.QUEUED

    # Simulate connectivity returning: worker drains the queue.
    sent = []
    monkeypatch.setattr(
        "app.services.dispatch.queue.send_certificate_email",
        lambda org, cert, r: sent.append(r))
    processed = process_queue(db)
    assert processed == 1
    job = db.query(DispatchJob).first()
    assert job.status == DispatchStatus.SENT
    assert sent == ["beta@example.com"]


def test_queue_retries_and_fails_after_max_attempts(db, sample_xlsx, monkeypatch):
    import_depot_workbook(db, sample_xlsx, "sample.xlsx")
    cert = generate_certificate(db, "444455556666", "2025-26")
    get_org_settings(db).dispatch_mode = "offline"
    db.commit()
    jobs = enqueue_dispatch(db, cert, DispatchChannel.WHATSAPP,
                            ["+8801711111111"], override_reason="ok", user="t")

    def boom(org, cert, r):
        raise RuntimeError("network down")
    monkeypatch.setattr(
        "app.services.dispatch.queue.send_certificate_whatsapp", boom)

    for _ in range(6):
        process_queue(db)
    job = db.get(DispatchJob, jobs[0].id)
    assert job.status == DispatchStatus.FAILED
    assert job.attempts == 5
    assert "network down" in job.last_error


def test_send_test_email_uses_settings_and_recipient(db, monkeypatch):
    org = get_org_settings(db)
    org.company_name = "Acme Ltd"
    org.officer_email = "officer@example.com"
    org.smtp_host = "smtp.example.com"
    org.smtp_port = 587
    org.smtp_from = "tax@example.com"
    org.smtp_user = "tax@example.com"
    org.smtp_password = "app-password"
    org.smtp_use_tls = True
    db.commit()

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["connect"] = (host, port, timeout)

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["to"] = msg["To"]
            sent["from"] = msg["From"]
            sent["subject"] = msg["Subject"]

        def quit(self):
            sent["quit"] = True

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    assert send_test_email(org) == "officer@example.com"
    assert sent["connect"] == ("smtp.example.com", 587, 30)
    assert sent["tls"] is True
    assert sent["login"] == ("tax@example.com", "app-password")
    assert sent["to"] == "officer@example.com"
    assert "tax@example.com" in sent["from"]
    assert sent["subject"] == "Tax Certificate SMTP test"


def test_send_test_email_reports_auth_failure(db, monkeypatch):
    org = get_org_settings(db)
    org.smtp_host = "smtp.example.com"
    org.smtp_from = "tax@example.com"
    org.smtp_user = "tax@example.com"
    org.smtp_password = "bad"
    db.commit()

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"Invalid credentials")

        def quit(self):
            pass

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    with pytest.raises(RuntimeError, match="SMTP authentication failed"):
        send_test_email(org, "officer@example.com")


def test_whatsapp_cloud_sends_document_without_caption_link(db, monkeypatch):
    org = get_org_settings(db)
    org.wa_provider = "cloud"
    org.wa_token = "token"
    org.wa_phone_number_id = "phone-id"
    db.commit()
    cert = Certificate(id=123, certificate_no="ACME/2025-26/1", period="2025-26")
    sent = {}

    class FakeResp:
        def raise_for_status(self):
            sent["raised"] = False

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["url"] = url
        sent["headers"] = headers
        sent["json"] = json
        sent["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr(
        "app.services.dispatch.whatsapp_sender.get_settings",
        lambda: SimpleNamespace(
            public_base_url="https://tax.example.com",
            link_signing_secret="test-secret",
        ),
    )

    send_certificate_whatsapp(org, cert, "+8801711111111")

    doc = sent["json"]["document"]
    assert sent["json"]["type"] == "document"
    assert "/public/certificates/123" in doc["link"]
    assert "Download:" not in doc["caption"]
    assert "http" not in doc["caption"]
    assert doc["filename"] == "ACME_2025-26_1.pdf"


def test_whatsapp_twilio_sends_media_without_body_link(db, monkeypatch):
    org = get_org_settings(db)
    org.wa_provider = "twilio"
    org.wa_twilio_sid = "sid"
    org.wa_twilio_auth = "auth"
    org.wa_twilio_from = "+15550000000"
    db.commit()
    cert = Certificate(id=456, certificate_no="ACME/2025-26/2", period="2025-26")
    sent = {}

    class FakeResp:
        def raise_for_status(self):
            sent["raised"] = False

    def fake_post(url, auth=None, data=None, timeout=None):
        sent["url"] = url
        sent["auth"] = auth
        sent["data"] = data
        sent["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr(
        "app.services.dispatch.whatsapp_sender.get_settings",
        lambda: SimpleNamespace(
            public_base_url="https://tax.example.com",
            link_signing_secret="test-secret",
        ),
    )

    send_certificate_whatsapp(org, cert, "+8801711111111")

    assert "/public/certificates/456" in sent["data"]["MediaUrl"]
    assert "Download:" not in sent["data"]["Body"]
    assert "http" not in sent["data"]["Body"]


def test_whatsapp_document_send_rejects_localhost_base_url(db, monkeypatch):
    org = get_org_settings(db)
    org.wa_provider = "cloud"
    org.wa_token = "token"
    org.wa_phone_number_id = "phone-id"
    db.commit()
    cert = Certificate(id=789, certificate_no="ACME/2025-26/3", period="2025-26")
    monkeypatch.setattr(
        "app.services.dispatch.whatsapp_sender.get_settings",
        lambda: SimpleNamespace(
            public_base_url="http://localhost:8000",
            link_signing_secret="test-secret",
        ),
    )

    with pytest.raises(RuntimeError, match="public HTTPS PUBLIC_BASE_URL"):
        send_certificate_whatsapp(org, cert, "+8801711111111")


# ------------------------------------------------------ Rate hook -----------
def test_rate_hook_anomalies(db):
    r = rate_hook.apply_rate_updates(db, [
        rate_hook.RateUpdate(section="89", kind="tds", rate=0.05),
    ])
    assert r["applied"] == 1 and not r["anomalies"]
    # 5% -> 9% is an 80% relative jump -> flagged but applied.
    r = rate_hook.apply_rate_updates(db, [
        rate_hook.RateUpdate(section="89", kind="tds", rate=0.09,
                             effective_from=date(2026, 2, 1)),
    ])
    assert r["applied"] == 1
    assert any("Unexpected rate change" in m for m in r["anomalies"])
    # invalid kind / out-of-range rate rejected
    r = rate_hook.apply_rate_updates(db, [
        rate_hook.RateUpdate(section="89", kind="xyz", rate=0.05),
        rate_hook.RateUpdate(section="90", kind="tds", rate=5.0),
    ])
    assert r["applied"] == 0 and len(r["anomalies"]) == 2
