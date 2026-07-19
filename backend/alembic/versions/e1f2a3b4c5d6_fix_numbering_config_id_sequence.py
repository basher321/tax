"""fix missing sequence default on tds_numbering_config.id

Revision ID: e1f2a3b4c5d6
Revises: c7d8e9f0a1b2
Create Date: 2026-07-18 18:00:00.000000

The pre-multi-company NumberingConfig model had `default=1` (a Python-side
ORM default) on its `id` column, used for the old single-row-per-app
pattern. On Postgres, SQLAlchemy suppresses the automatic SERIAL/sequence
DDL for an integer primary key when a client-side default is already
configured. Any database whose tds_numbering_config table was created via
the app's dev-convenience Base.metadata.create_all() (rather than this
migration chain) therefore has a plain `id INTEGER NOT NULL PRIMARY KEY`
with no sequence at all. Once the multi-company migration removed that
Python-side default (id is now assigned per-company, not always 1),
SQLAlchemy stopped supplying an explicit id — and Postgres has nothing to
generate one, so every new NumberingConfig insert fails with a NOT NULL
violation on id (found via live testing against a real pre-existing
Postgres database).

This migration is defensive/idempotent: it only acts if the column
genuinely has no default configured, and is a no-op on SQLite (whose
INTEGER PRIMARY KEY auto-increments natively regardless of this issue).
"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    current_default = bind.execute(sa.text(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'tds_numbering_config' AND column_name = 'id'"
    )).scalar()
    if current_default is not None:
        return  # already has a sequence/default — nothing to fix

    bind.execute(sa.text(
        "CREATE SEQUENCE IF NOT EXISTS tds_numbering_config_id_seq"))
    bind.execute(sa.text(
        "ALTER SEQUENCE tds_numbering_config_id_seq OWNED BY tds_numbering_config.id"))
    bind.execute(sa.text(
        "SELECT setval('tds_numbering_config_id_seq', "
        "COALESCE((SELECT MAX(id) FROM tds_numbering_config), 0) + 1, false)"))
    bind.execute(sa.text(
        "ALTER TABLE tds_numbering_config ALTER COLUMN id "
        "SET DEFAULT nextval('tds_numbering_config_id_seq')"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    bind.execute(sa.text(
        "ALTER TABLE tds_numbering_config ALTER COLUMN id DROP DEFAULT"))
    bind.execute(sa.text(
        "DROP SEQUENCE IF EXISTS tds_numbering_config_id_seq"))
