"""add email to signatures

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-18 20:00:00.000000

Each named signatory now carries an email alongside name/designation, shown
on the certificate footer next to their signature image.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tds_signatures') as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tds_signatures') as batch_op:
        batch_op.drop_column('email')
