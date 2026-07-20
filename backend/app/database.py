"""SQLAlchemy engine/session factory.

The module is host-app agnostic: it only needs a DATABASE_URL. All tables
are namespaced with the ``tds_`` prefix so they can coexist inside an
existing ERP schema without collisions.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()


def _sync_database_url(url: str) -> str:
    async_drivers = ("postgresql+asyncpg://",)
    if url.startswith(async_drivers):
        raise ValueError(
            "DATABASE_URL uses an async SQLAlchemy driver, but this app is "
            "configured with synchronous SQLAlchemy sessions. Use a sync URL "
            "such as postgresql+psycopg2://..."
        )
    return url


engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    # Needed for SQLite when the FastAPI app + background worker share the DB.
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif "+pg8000" in settings.database_url:
    # pg8000 (pure-Python, no libpq/OpenSSL binary) needs an explicit SSL
    # context to reach Supabase's TLS-only pooler — psycopg2 negotiated this
    # automatically via libpq defaults, pg8000 does not.
    engine_kwargs["connect_args"] = {"ssl_context": True}

engine = create_engine(_sync_database_url(settings.database_url), **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
