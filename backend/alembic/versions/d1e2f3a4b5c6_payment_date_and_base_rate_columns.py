"""payment date, base amount / tds rate, and certificate-line transaction links

Revision ID: d1e2f3a4b5c6
Revises: c5d6e7f8a9b0
Create Date: 2026-07-23 12:00:00.000000

Adds:
  * tds_transactions.base_amount / tds_rate — stored as their own columns
    (previously only used transiently during import) so the Import page can
    display them for an already-persisted row.
  * tds_certificates.payment_date — the new editable Row 5 "Payment Date"
    field, replacing the printed "Period for which payment is made From/To"
    text. period_from/period_to are untouched (still used for grouping and
    the existing date-range search).
  * tds_certificate_lines.transaction_id / tds_certificate_challan_lines.transaction_id
    — nullable link back to the Transaction row a certificate line was
    generated from, so an in-place edit on the certificate can propagate
    back to the original imported row. NULL for certificates generated
    before this migration.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5c6'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tds_transactions') as batch_op:
        batch_op.add_column(sa.Column('base_amount', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('tds_rate', sa.Float(), nullable=True))

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.add_column(sa.Column('payment_date', sa.Date(), nullable=True))

    with op.batch_alter_table('tds_certificate_lines') as batch_op:
        batch_op.add_column(sa.Column('transaction_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_cert_line_transaction', 'tds_transactions', ['transaction_id'], ['id']
        )

    with op.batch_alter_table('tds_certificate_challan_lines') as batch_op:
        batch_op.add_column(sa.Column('transaction_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_cert_challan_line_transaction', 'tds_transactions', ['transaction_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('tds_certificate_challan_lines') as batch_op:
        batch_op.drop_constraint('fk_cert_challan_line_transaction', type_='foreignkey')
        batch_op.drop_column('transaction_id')

    with op.batch_alter_table('tds_certificate_lines') as batch_op:
        batch_op.drop_constraint('fk_cert_line_transaction', type_='foreignkey')
        batch_op.drop_column('transaction_id')

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.drop_column('payment_date')

    with op.batch_alter_table('tds_transactions') as batch_op:
        batch_op.drop_column('tds_rate')
        batch_op.drop_column('base_amount')
