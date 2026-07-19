"""remove company logo and per-certificate signature selection

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-18 19:00:00.000000

Per the latest spec: item 1 removes the company logo feature entirely
(dead code, not just hidden), and items 2/3/5 replace "pick one signature
at generation time" with "every enabled named signature renders on every
certificate." Concretely:

  - drop tds_companies.logo_path
  - drop tds_certificates.signature_id (and its FK) — no longer
    per-certificate; certificate PDFs now query all enabled signatures for
    the certificate's company at render time
  - tds_signatures gains `enabled` (bool, default True — every signature
    migrated from the old single-signature setup, or created before this
    change, stays visible on certificates exactly as before) and
    `designation` (nullable text, new optional field); drops `is_default`,
    which no longer means anything now that there's no single "the"
    signature to default to
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.drop_constraint('fk_certificates_signature', type_='foreignkey')
        batch_op.drop_column('signature_id')

    with op.batch_alter_table('tds_companies') as batch_op:
        batch_op.drop_column('logo_path')

    with op.batch_alter_table('tds_signatures') as batch_op:
        batch_op.add_column(sa.Column('designation', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column(
            'enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.drop_column('is_default')


def downgrade() -> None:
    with op.batch_alter_table('tds_signatures') as batch_op:
        batch_op.add_column(sa.Column(
            'is_default', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.drop_column('enabled')
        batch_op.drop_column('designation')

    with op.batch_alter_table('tds_companies') as batch_op:
        batch_op.add_column(sa.Column('logo_path', sa.String(length=512), nullable=True))

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.add_column(sa.Column('signature_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_certificates_signature', 'tds_signatures', ['signature_id'], ['id'])
