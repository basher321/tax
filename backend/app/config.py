"""Application configuration loaded from environment variables."""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DB. Defaults to a local SQLite file for zero-config development;
    # point DATABASE_URL at PostgreSQL in production, e.g.
    # postgresql+psycopg2://user:pass@host:5432/erp
    database_url: str = "sqlite:///./tax_certificates.db"

    # Directory where generated PDFs and uploaded images (logo, seal) live.
    storage_dir: str = "./storage"

    # Secret used to sign hosted-PDF links sent over WhatsApp.
    link_signing_secret: str = "change-me"

    # Base URL of this service, used to build hosted certificate links.
    public_base_url: str = "http://localhost:8000"

    # Dispatch queue worker poll interval (seconds) for offline mode.
    dispatch_poll_seconds: int = 30

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
