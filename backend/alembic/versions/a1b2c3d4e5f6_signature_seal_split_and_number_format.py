"""signature/seal split fields and configurable number_format

Revision ID: a1b2c3d4e5f6
Revises: eb07c9c490e5
Create Date: 2026-07-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'e8fd48028372'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Item 8: separate signature/seal images, additive — the legacy combined
    # seal_signature_path column and its data are untouched.
    op.add_column('tds_org_settings', sa.Column('signature_path', sa.String(length=512), nullable=True))
    op.add_column('tds_org_settings', sa.Column('seal_path', sa.String(length=512), nullable=True))

    # Item 9: admin-editable certificate number format. The default value
    # reproduces the previously-hardcoded "{company}{sep}{fy}{sep}{number}"
    # output exactly, so existing certificate numbers stay unaffected.
    op.add_column(
        'tds_numbering_config',
        sa.Column(
            'number_format', sa.String(length=128), nullable=False,
            server_default='{CompanyName}{sep}{FiscalYear}{sep}{AutoNumber}',
        ),
    )


def downgrade() -> None:
    op.drop_column('tds_numbering_config', 'number_format')
    op.drop_column('tds_org_settings', 'seal_path')
    op.drop_column('tds_org_settings', 'signature_path')
