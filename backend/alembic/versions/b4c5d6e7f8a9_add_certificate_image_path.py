"""add certificate.image_path (share-ready JPEG rasterized from the PDF)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-19 10:00:00.000000

Adds the certificate-image export feature: a high-resolution JPEG rasterized
directly from the already-rendered PDF (same source, so it's pixel-identical
to it), sized for WhatsApp/email sharing without WhatsApp's own aggressive
re-compression. Existing certificates get image_path=NULL until their PDF is
next (re)generated, at which point it's backfilled automatically.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.add_column(sa.Column('image_path', sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.drop_column('image_path')
