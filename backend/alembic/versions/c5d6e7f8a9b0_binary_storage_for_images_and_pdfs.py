"""store uploaded images and generated PDFs in the database, not on disk

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-20 09:00:00.000000

Moves every uploaded image (company seal, letterhead header/footer, named
signatures, legacy org settings) and every generated certificate PDF/share
image from local-disk paths to bytea columns in Postgres. This is required
to run the backend as stateless/serverless functions (e.g. Vercel), which
give every invocation a fresh, empty filesystem — a path saved during one
request is not guaranteed to exist by the time a later request reads it.

This migration cannot carry over the *contents* of files that only exist on
a previous host's local disk (no access to that filesystem from here) — old
uploaded images and previously generated certificate PDFs/share images are
NOT migrated and will need to be re-uploaded / regenerated (certificates
regenerate automatically the next time they're saved or their PDF/image is
requested; company/signature images need a manual re-upload in Settings).
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tds_companies') as batch_op:
        batch_op.add_column(sa.Column('seal_data', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('letterhead_header_data', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('letterhead_footer_data', sa.LargeBinary(), nullable=True))
        batch_op.drop_column('seal_path')
        batch_op.drop_column('letterhead_header_path')
        batch_op.drop_column('letterhead_footer_path')

    with op.batch_alter_table('tds_signatures') as batch_op:
        batch_op.add_column(sa.Column('image_data', sa.LargeBinary(), nullable=True))
        batch_op.drop_column('image_path')

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.add_column(sa.Column('pdf_data', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('image_data', sa.LargeBinary(), nullable=True))
        batch_op.drop_column('pdf_path')
        batch_op.drop_column('image_path')

    with op.batch_alter_table('tds_org_settings') as batch_op:
        batch_op.add_column(sa.Column('logo_data', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('seal_signature_data', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('signature_data', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('seal_data', sa.LargeBinary(), nullable=True))
        batch_op.drop_column('logo_path')
        batch_op.drop_column('seal_signature_path')
        batch_op.drop_column('signature_path')
        batch_op.drop_column('seal_path')


def downgrade() -> None:
    with op.batch_alter_table('tds_org_settings') as batch_op:
        batch_op.add_column(sa.Column('seal_path', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('signature_path', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('seal_signature_path', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('logo_path', sa.String(length=512), nullable=True))
        batch_op.drop_column('seal_data')
        batch_op.drop_column('signature_data')
        batch_op.drop_column('seal_signature_data')
        batch_op.drop_column('logo_data')

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.add_column(sa.Column('image_path', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('pdf_path', sa.String(length=512), nullable=True))
        batch_op.drop_column('image_data')
        batch_op.drop_column('pdf_data')

    with op.batch_alter_table('tds_signatures') as batch_op:
        batch_op.add_column(sa.Column('image_path', sa.String(length=512), nullable=False,
                                      server_default=''))
        batch_op.drop_column('image_data')

    with op.batch_alter_table('tds_companies') as batch_op:
        batch_op.add_column(sa.Column('letterhead_footer_path', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('letterhead_header_path', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('seal_path', sa.String(length=512), nullable=True))
        batch_op.drop_column('letterhead_footer_data')
        batch_op.drop_column('letterhead_header_data')
        batch_op.drop_column('seal_data')
