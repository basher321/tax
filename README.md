# Tax Deduction Certificate Module

A self-contained ERP module that imports supplier tax data from Excel,
auto-generates **Certificate of Deduction of Tax** documents (Section 145,
Income Tax Act 2023) in a **fixed, locked layout**, and dispatches them by
Email and WhatsApp with online/offline queueing.

**Stack:** FastAPI + SQLAlchemy + PostgreSQL (SQLite for dev) · React + Tailwind · openpyxl/pandas · ReportLab.

```
tax-certificate-module/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + offline-queue worker
│   │   ├── config.py, database.py
│   │   ├── models/entities.py       # normalized schema (tds_* tables)
│   │   ├── schemas/                 # Pydantic I/O models
│   │   ├── api/routes.py            # /api/* + signed public PDF links
│   │   └── services/
│   │       ├── excel_import.py      # Depot-SCB + challan file import
│   │       ├── aggregation.py       # INDEX/FILTER/SUM logic in Python
│   │       ├── certificate_generator.py
│   │       ├── numbering.py         # atomic sequential allocation
│   │       ├── pdf_renderer.py      # fixed layout (certificate_format.jpeg)
│   │       ├── amount_in_words.py
│   │       ├── validation.py        # pre-dispatch anomaly checks
│   │       ├── rate_hook.py         # TDS/VDS/VAT rate-scraper interface
│   │       └── dispatch/            # email, whatsapp, online/offline queue
│   ├── alembic/                     # migrations
│   └── tests/test_module.py
└── frontend/                        # React + Vite + Tailwind (4-item sidebar)
```

## Setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env             # edit values

# Migrations (PostgreSQL in production; SQLite works out of the box for dev)
export DATABASE_URL="postgresql+psycopg2://erp:erp@localhost:5432/erp"
alembic upgrade head

uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 — proxies /api to :8000
```

## Environment variables (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL (Postgres in prod) | `sqlite:///./tax_certificates.db` |
| `STORAGE_DIR` | PDFs + uploaded images | `./storage` |
| `PUBLIC_BASE_URL` | Base URL for WhatsApp hosted-PDF links | `http://localhost:8000` |
| `LINK_SIGNING_SECRET` | HMAC secret for hosted links | change it |
| `DISPATCH_POLL_SECONDS` | Offline queue drain interval | `30` |

SMTP and WhatsApp credentials are **not** env vars — they are configured at
runtime in the Settings screen and stored in `tds_org_settings`.

## Walkthrough with `Challan Record(3).xlsx`

1. **Settings** → fill company name/address, upload the seal+signature PNG,
   enter the designated officer (name, designation, email), set numbering
   (e.g. company token `Renata PLC`, width 1, per-fiscal-year reset), and
   your SMTP/WhatsApp credentials.
2. **Import** → upload `Challan Record(3).xlsx`. The Depot-SCB sheet's 3,269
   rows import; rows missing a TIN (73 in this file) appear in the row-level
   error table with the exact Excel row number and problem. Fix in Excel and
   re-upload, or proceed — good rows are already in.
   * The second uploader accepts **challan files** and back-fills
     `Challan No., Challan Date, Total Challan Amount, Section` onto matching
     supplier/month records.
3. **Certificate Issue** → the *Pending* table shows one row per unique
   `(TIN, fiscal-year)` grouping (451 for this file). Click **Generate
   Certificate** per row or tick several and **Generate selected**.
   Numbers allocate sequentially: `Renata PLC/2025-26/1`, `/2`, …
4. Click **Preview / send**: the certificate renders in the fixed layout.
   Only **Remarks** is editable — saving re-renders the PDF. Anomalies
   (missing email/WhatsApp/TIN/challan, TDS-rate mismatches, duplicates,
   missing seal/officer) block sending until fixed or overridden with a
   logged reason.
5. Dispatch with **Send email** (PDF attached via your SMTP), **Send
   WhatsApp** (signed hosted PDF link / document message), **Print**, or
   **Download PDF**. In *offline* dispatch mode jobs queue and are sent
   automatically when connectivity returns (or via `POST /api/dispatch/process`).

## Rate-scraper integration

The existing rate automation pushes updates to:

```
POST /api/rates/update
[{"section": "89", "kind": "tds", "rate": 0.05, "effective_from": "2026-07-01"}]

POST /api/rates/scrape-failure   {"message": "..."}
GET  /api/rates/anomalies
```

Rates apply to reconciliation checks going forward. Out-of-range rates,
unknown kinds, >50% jumps, and scrape failures raise anomaly records.

## Design decisions worth knowing

* **Fixed layout.** `pdf_renderer.py` is the single source of truth for the
  certificate layout, mirroring `certificate_format.jpeg` (header, payee
  block, Section 06/07 tables with a 20-row minimum that grows as needed,
  amount-in-words, officer footer, seal with the auto date beneath it). No
  UI or API exposes layout configuration.
* **No Excel formulas at runtime.** The template's
  `INDEX(FILTER(...))`/`SUM` mapping is reimplemented in
  `services/aggregation.py`: Depot-SCB rows → group by `(TIN, period)` →
  ordered Section 06 lines + mirrored Section 07 challan lines → totals.
* **All 21 columns preserved** exactly as named (see
  `excel_import.SOURCE_COLUMNS`); `BIN` is a first-class supplier field with
  manual entry via `PATCH /api/suppliers/{id}`.
* **Supplier-only** enforcement lives in `generate_certificate()` — a
  non-supplier party raises `GenerationError` regardless of the caller.
* **Concurrency-safe numbering** via an atomic
  `UPDATE ... SET last_value = last_value + 1 RETURNING` on
  `tds_number_sequences` (row lock on Postgres, write lock on SQLite);
  covered by a 20-thread test.
* **Multiple contacts** per supplier (`tds_supplier_contacts`) — any number
  of emails and WhatsApp numbers; dispatch defaults to all of the chosen kind.

## Tests

```bash
cd backend && pytest tests/ -v
```

Covers: Excel import parsing + row-level validation, aggregation math against
a known sample, amount-in-words, supplier-only and duplicate rules,
**concurrent certificate-number allocation (20 threads)**, every anomaly
rule, offline-queue block → override → drain behavior, retry/max-attempt
failure, and rate-hook anomaly detection.

## Railway deployment

This repository is ready for Railway as a single Docker-backed service. The
root `Dockerfile` builds the React frontend, installs the FastAPI backend, and
serves the built app from FastAPI. Railway will use the root `Dockerfile`
automatically.

1. Create a new Railway project from this repository.
2. Add a PostgreSQL service in the same Railway project.
3. In the app service variables, set:

```text
DATABASE_URL=${{ Postgres.DATABASE_URL }}
PUBLIC_BASE_URL=https://your-railway-domain.up.railway.app
LINK_SIGNING_SECRET=replace-with-a-long-random-string
DISPATCH_POLL_SECONDS=30
```

For uploaded logos, seal images, and generated PDFs, add a Railway volume to
the app service and mount it at `/app/storage`. The Dockerfile defaults
`STORAGE_DIR` to `/app/storage`, so those files persist across redeploys.

The deployed health check is:

```text
/api/health
```
