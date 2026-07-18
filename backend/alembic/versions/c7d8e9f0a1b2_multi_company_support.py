"""multi-company support: companies, signatures, company-scoped data

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18 12:00:00.000000

Adds tds_companies / tds_signatures, scopes suppliers/transactions/
import_batches/certificates/numbering_config to a company, and backfills a
single default Company from the existing tds_org_settings row so pre-existing
data keeps working unchanged. SMTP/WhatsApp/dispatch settings on
tds_org_settings are untouched — they stay global.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = 'c7d8e9f0a1b2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---- new tables -----------------------------------------------------
    op.create_table(
        'tds_companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('logo_path', sa.String(length=512), nullable=True),
        sa.Column('seal_path', sa.String(length=512), nullable=True),
        sa.Column('letterhead_header_path', sa.String(length=512), nullable=True),
        sa.Column('letterhead_footer_path', sa.String(length=512), nullable=True),
        sa.Column('officer_name', sa.String(length=255), nullable=True),
        sa.Column('officer_designation', sa.String(length=255), nullable=True),
        sa.Column('officer_email', sa.String(length=255), nullable=True),
        sa.Column('default_bank_name', sa.String(length=255), nullable=True),
        sa.Column('default_description', sa.String(length=255), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'tds_signatures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('image_path', sa.String(length=512), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['tds_companies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'name'),
    )
    op.create_index(op.f('ix_tds_signatures_company_id'), 'tds_signatures', ['company_id'], unique=False)

    # ---- add nullable company_id (+ cert extras) to existing tables -----
    op.add_column('tds_suppliers', sa.Column('company_id', sa.Integer(), nullable=True))
    op.add_column('tds_transactions', sa.Column('company_id', sa.Integer(), nullable=True))
    op.add_column('tds_import_batches', sa.Column('company_id', sa.Integer(), nullable=True))
    op.add_column('tds_certificates', sa.Column('company_id', sa.Integer(), nullable=True))
    op.add_column('tds_certificates', sa.Column('signature_id', sa.Integer(), nullable=True))
    op.add_column('tds_certificates', sa.Column(
        'issue_date_mode', sa.String(length=10), nullable=False, server_default='auto'))
    op.add_column('tds_numbering_config', sa.Column('company_id', sa.Integer(), nullable=True))

    # ---- backfill: seed one default Company from tds_org_settings -------
    org = bind.execute(sa.text(
        "SELECT company_name, company_address, logo_path, seal_path, "
        "signature_path, officer_name, officer_designation, officer_email, "
        "default_bank_name, default_description FROM tds_org_settings LIMIT 1"
    )).fetchone()

    company_name = (org and org[0]) or "Default Company"
    now = datetime.utcnow()
    company_id = bind.execute(
        sa.text(
            "INSERT INTO tds_companies "
            "(name, address, logo_path, seal_path, officer_name, officer_designation, "
            "officer_email, default_bank_name, default_description, is_default, created_at) "
            "VALUES (:name, :address, :logo_path, :seal_path, :officer_name, :officer_designation, "
            ":officer_email, :default_bank_name, :default_description, :is_default, :created_at) "
            "RETURNING id"
        ).bindparams(
            sa.bindparam('is_default', value=True, type_=sa.Boolean()),
        ),
        {
            "name": company_name,
            "address": org[1] if org else None,
            "logo_path": org[2] if org else None,
            "seal_path": org[3] if org else None,
            "officer_name": org[5] if org else None,
            "officer_designation": org[6] if org else None,
            "officer_email": org[7] if org else None,
            "default_bank_name": org[8] if org else None,
            "default_description": (org[9] if org else None) or "Supply of Goods",
            "created_at": now,
        },
    ).scalar_one()

    if org and org[4]:  # signature_path was set on the legacy singleton
        bind.execute(
            sa.text(
                "INSERT INTO tds_signatures (company_id, name, image_path, is_default, created_at) "
                "VALUES (:company_id, :name, :image_path, :is_default, :created_at)"
            ).bindparams(sa.bindparam('is_default', value=True, type_=sa.Boolean())),
            {"company_id": company_id, "name": "Default", "image_path": org[4],
             "created_at": now},
        )

    for table in ("tds_suppliers", "tds_transactions", "tds_import_batches", "tds_certificates"):
        bind.execute(sa.text(f"UPDATE {table} SET company_id = :cid WHERE company_id IS NULL"),
                    {"cid": company_id})
    bind.execute(sa.text(
        "UPDATE tds_numbering_config SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": company_id})

    # ---- tighten constraints now that every row has a company_id --------
    with op.batch_alter_table('tds_suppliers') as batch_op:
        batch_op.alter_column('company_id', nullable=False)
        batch_op.drop_index('ix_tds_suppliers_tin')
        batch_op.create_index('ix_tds_suppliers_tin', ['tin'], unique=False)
        batch_op.create_index(op.f('ix_tds_suppliers_company_id'), ['company_id'], unique=False)
        batch_op.create_unique_constraint('uq_supplier_company_tin', ['company_id', 'tin'])
        batch_op.create_foreign_key(
            'fk_suppliers_company', 'tds_companies', ['company_id'], ['id'])

    with op.batch_alter_table('tds_transactions') as batch_op:
        batch_op.alter_column('company_id', nullable=False)
        batch_op.create_index(op.f('ix_tds_transactions_company_id'), ['company_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_transactions_company', 'tds_companies', ['company_id'], ['id'])

    with op.batch_alter_table('tds_import_batches') as batch_op:
        batch_op.alter_column('company_id', nullable=False)
        batch_op.create_index(op.f('ix_tds_import_batches_company_id'), ['company_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_import_batches_company', 'tds_companies', ['company_id'], ['id'])

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.alter_column('company_id', nullable=False)
        batch_op.drop_constraint('uq_cert_tin_period', type_='unique')
        batch_op.create_unique_constraint(
            'uq_cert_company_tin_period', ['company_id', 'tin', 'period'])
        batch_op.create_index(op.f('ix_tds_certificates_company_id'), ['company_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_certificates_company', 'tds_companies', ['company_id'], ['id'])
        batch_op.create_foreign_key(
            'fk_certificates_signature', 'tds_signatures', ['signature_id'], ['id'])

    with op.batch_alter_table('tds_numbering_config') as batch_op:
        batch_op.create_unique_constraint('uq_numbering_config_company', ['company_id'])
        batch_op.create_foreign_key(
            'fk_numbering_config_company', 'tds_companies', ['company_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('tds_numbering_config') as batch_op:
        batch_op.drop_constraint('fk_numbering_config_company', type_='foreignkey')
        batch_op.drop_constraint('uq_numbering_config_company', type_='unique')
        batch_op.drop_column('company_id')

    with op.batch_alter_table('tds_certificates') as batch_op:
        batch_op.drop_constraint('fk_certificates_signature', type_='foreignkey')
        batch_op.drop_constraint('fk_certificates_company', type_='foreignkey')
        batch_op.drop_index(op.f('ix_tds_certificates_company_id'))
        batch_op.drop_constraint('uq_cert_company_tin_period', type_='unique')
        batch_op.create_unique_constraint('uq_cert_tin_period', ['tin', 'period'])
        batch_op.drop_column('issue_date_mode')
        batch_op.drop_column('signature_id')
        batch_op.drop_column('company_id')

    with op.batch_alter_table('tds_import_batches') as batch_op:
        batch_op.drop_constraint('fk_import_batches_company', type_='foreignkey')
        batch_op.drop_index(op.f('ix_tds_import_batches_company_id'))
        batch_op.drop_column('company_id')

    with op.batch_alter_table('tds_transactions') as batch_op:
        batch_op.drop_constraint('fk_transactions_company', type_='foreignkey')
        batch_op.drop_index(op.f('ix_tds_transactions_company_id'))
        batch_op.drop_column('company_id')

    with op.batch_alter_table('tds_suppliers') as batch_op:
        batch_op.drop_constraint('fk_suppliers_company', type_='foreignkey')
        batch_op.drop_constraint('uq_supplier_company_tin', type_='unique')
        batch_op.drop_index(op.f('ix_tds_suppliers_company_id'))
        batch_op.drop_index('ix_tds_suppliers_tin')
        batch_op.create_index('ix_tds_suppliers_tin', ['tin'], unique=True)
        batch_op.drop_column('company_id')

    op.drop_index(op.f('ix_tds_signatures_company_id'), table_name='tds_signatures')
    op.drop_table('tds_signatures')
    op.drop_table('tds_companies')
