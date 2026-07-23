"""FastAPI application entrypoint.

Self-contained module: mount `app` inside a host ERP or run standalone.
A lightweight background loop drains the offline dispatch queue.
"""
import asyncio
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import public_router, router
from .config import get_settings
from .database import Base, SessionLocal, engine
from .services.dispatch import process_queue


async def _queue_worker():
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.dispatch_poll_seconds)
        db = SessionLocal()
        try:
            process_queue(db)
        except Exception:  # noqa: BLE001 — worker must never die
            pass
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience; use Alembic migrations in production.
    Base.metadata.create_all(engine)
    # The background poller only makes sense on a persistent server: on
    # serverless (Vercel sets VERCEL=1), each invocation is a fresh, isolated
    # process that doesn't outlive its request, so a background asyncio task
    # here would never actually run between requests. The offline dispatch
    # queue still drains on demand via POST /api/dispatch/process — wire a
    # Vercel Cron Job (or any external scheduler) to call it periodically.
    task = None if os.environ.get("VERCEL") else asyncio.create_task(_queue_worker())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Tax Deduction Certificate Module", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.include_router(router)
app.include_router(public_router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/admin/migrate-d1e2f3a4b5c6")
def _run_migration_d1e2f3a4b5c6(secret: str):
    """TEMPORARY, one-off: applies migration d1e2f3a4b5c6 (Payment Date,
    Base Amount/TDS Rate, and certificate-line transaction links) directly
    via SQL, since alembic itself is intentionally not a runtime dependency
    here (see pyproject.toml — kept out to stay under Vercel's function size
    limit). Mirrors that migration's upgrade() body exactly, idempotently
    (IF NOT EXISTS), and records it in alembic_version so a future `alembic
    upgrade head` run from a normal checkout doesn't try to re-apply it.
    Remove this endpoint once the migration has been applied."""
    from sqlalchemy import text

    expected = os.environ.get("MIGRATION_SECRET")
    if not expected or secret != expected:
        raise HTTPException(403, "Forbidden")

    statements = [
        "ALTER TABLE tds_transactions ADD COLUMN IF NOT EXISTS base_amount DOUBLE PRECISION",
        "ALTER TABLE tds_transactions ADD COLUMN IF NOT EXISTS tds_rate DOUBLE PRECISION",
        "ALTER TABLE tds_certificates ADD COLUMN IF NOT EXISTS payment_date DATE",
        "ALTER TABLE tds_certificate_lines ADD COLUMN IF NOT EXISTS transaction_id INTEGER REFERENCES tds_transactions(id)",
        "ALTER TABLE tds_certificate_challan_lines ADD COLUMN IF NOT EXISTS transaction_id INTEGER REFERENCES tds_transactions(id)",
        "UPDATE alembic_version SET version_num = 'd1e2f3a4b5c6' WHERE version_num = 'c5d6e7f8a9b0'",
    ]
    applied = []
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
            applied.append(stmt)
    return {"ok": True, "applied": applied}


def _frontend_dist() -> Path | None:
    candidates = [
        os.environ.get("FRONTEND_DIST"),
        str(Path(__file__).resolve().parents[2] / "frontend_dist"),
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if (path / "index.html").exists():
            return path
    return None


frontend_dist = _frontend_dist() if os.environ.get("SERVE_FRONTEND") == "1" else None
if frontend_dist:
    assets = frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/{path:path}", response_class=HTMLResponse)
    def serve_frontend(path: str = ""):
        if path.startswith(("api/", "public/")):
            raise HTTPException(404, "Not found")
        return (frontend_dist / "index.html").read_text(encoding="utf-8")
