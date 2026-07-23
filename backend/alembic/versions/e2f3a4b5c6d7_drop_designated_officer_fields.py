"""drop designated officer name/designation/email fields

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-23 16:00:00.000000

Removes officer_name / officer_designation / officer_email from both
tds_companies and tds_org_settings. These were never rendered on the
certificate PDF — they only backed the email "Regards," signoff, the SMTP
sender/recipient fallback, and an anomaly check gating dispatch, all of
which have been removed alongside the Settings UI fields.
"""
from alembic import op
import sqlalchemy as sa


revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tds_companies') as batch_op:
        batch_op.drop_column('officer_name')
        batch_op.drop_column('officer_designation')
        batch_op.drop_column('officer_email')

    with op.batch_alter_table('tds_org_settings') as batch_op:
        batch_op.drop_column('officer_name')
        batch_op.drop_column('officer_designation')
        batch_op.drop_column('officer_email')


def downgrade() -> None:
    with op.batch_alter_table('tds_org_settings') as batch_op:
        batch_op.add_column(sa.Column('officer_email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('officer_designation', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('officer_name', sa.String(length=255), nullable=True))

    with op.batch_alter_table('tds_companies') as batch_op:
        batch_op.add_column(sa.Column('officer_email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('officer_designation', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('officer_name', sa.String(length=255), nullable=True))
