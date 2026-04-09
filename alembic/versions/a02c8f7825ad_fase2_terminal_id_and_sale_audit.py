"""fase2_terminal_id_and_sale_audit

Revision ID: a02c8f7825ad
Revises: e2a9de11ecdb
Create Date: 2026-04-09 08:02:24.202264

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'a02c8f7825ad'
down_revision: Union[str, Sequence[str], None] = 'e2a9de11ecdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── 1. Create new tables ──────────────────────────────────────────
    op.create_table('dashboard_daily_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('sales_today', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('estimated_profit_today', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('critical_products', sa.Integer(), nullable=False),
        sa.Column('credits_receivable', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('pending_purchases', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('cash_expected', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('cash_difference', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dashboard_daily_snapshots_id'), 'dashboard_daily_snapshots', ['id'], unique=False)
    op.create_index(op.f('ix_dashboard_daily_snapshots_snapshot_date'), 'dashboard_daily_snapshots', ['snapshot_date'], unique=True)

    op.create_table('credits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('payment_method', sa.String(length=20), nullable=True),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credits_id'), 'credits', ['id'], unique=False)

    # ── 2. Drop FKs that reference tables we're about to drop ─────────
    op.drop_constraint('credit_sales_ibfk_1', 'credit_sales', type_='foreignkey')

    # ── 3. Drop old tables (order: children first) ────────────────────
    op.drop_index('ix_credit_payments_id', table_name='credit_payments')
    op.drop_table('credit_payments')
    op.drop_table('dashboard_snapshots')
    op.drop_index('ix_credit_accounts_id', table_name='credit_accounts')
    op.drop_table('credit_accounts')

    # ── 4. Alter existing tables ──────────────────────────────────────

    # -- ai_config --
    op.alter_column('ai_config', 'temperature',
        existing_type=mysql.FLOAT(),
        type_=sa.Numeric(precision=3, scale=2),
        existing_nullable=False,
        existing_server_default=sa.text("'0.3'"))

    # -- cash_movements --
    op.add_column('cash_movements', sa.Column('cash_session_id', sa.Integer(), nullable=False))
    op.add_column('cash_movements', sa.Column('type', sa.String(length=3), nullable=False))
    op.add_column('cash_movements', sa.Column('concept', sa.String(length=255), nullable=False))
    op.add_column('cash_movements', sa.Column('source', sa.String(length=50), nullable=True))
    op.add_column('cash_movements', sa.Column('reference_id', sa.Integer(), nullable=True))
    op.alter_column('cash_movements', 'amount',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        nullable=False)
    op.create_index(op.f('ix_cash_movements_id'), 'cash_movements', ['id'], unique=False)
    op.drop_constraint('cash_movements_ibfk_1', 'cash_movements', type_='foreignkey')
    op.create_foreign_key('fk_cash_movements_cash_session_id', 'cash_movements', 'cash_sessions', ['cash_session_id'], ['id'])
    op.drop_column('cash_movements', 'movement_type')
    op.drop_column('cash_movements', 'session_id')

    # -- cash_sessions --
    op.add_column('cash_sessions', sa.Column('date', sa.Date(), nullable=False))
    op.add_column('cash_sessions', sa.Column('terminal_id', sa.String(length=10), nullable=False))
    op.add_column('cash_sessions', sa.Column('expected_closing', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('cash_sessions', sa.Column('difference', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('cash_sessions', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.alter_column('cash_sessions', 'status',
        existing_type=mysql.VARCHAR(length=20),
        nullable=True,
        existing_server_default=sa.text("'OPEN'"))
    op.create_index(op.f('ix_cash_sessions_date'), 'cash_sessions', ['date'], unique=False)
    op.create_index(op.f('ix_cash_sessions_id'), 'cash_sessions', ['id'], unique=False)
    op.create_unique_constraint('uq_cash_date_terminal', 'cash_sessions', ['date', 'terminal_id'])
    op.drop_constraint('cash_sessions_ibfk_1', 'cash_sessions', type_='foreignkey')
    op.drop_column('cash_sessions', 'user_id')
    op.drop_column('cash_sessions', 'notes')
    op.drop_column('cash_sessions', 'opened_at')

    # -- categories --
    op.add_column('categories', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('categories', sa.Column('is_active', sa.Boolean(), nullable=False))
    op.add_column('categories', sa.Column('position', sa.Integer(), server_default='0', nullable=False))
    op.add_column('categories', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.alter_column('categories', 'icon',
        existing_type=mysql.VARCHAR(length=50),
        type_=sa.String(length=10),
        existing_nullable=True)
    op.create_index(op.f('ix_categories_id'), 'categories', ['id'], unique=False)
    op.drop_column('categories', 'color')

    # -- credit_sales (FK already dropped above) --
    op.add_column('credit_sales', sa.Column('customer_id', sa.Integer(), nullable=False))
    op.add_column('credit_sales', sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False))
    op.create_index(op.f('ix_credit_sales_id'), 'credit_sales', ['id'], unique=False)
    op.create_foreign_key('fk_credit_sales_customer_id', 'credit_sales', 'customers', ['customer_id'], ['id'])
    op.drop_column('credit_sales', 'credit_id')
    op.drop_column('credit_sales', 'amount')

    # -- customers --
    op.add_column('customers', sa.Column('secondary_phone', sa.String(length=20), nullable=True))
    op.add_column('customers', sa.Column('customer_type', sa.String(length=20), nullable=True))
    op.add_column('customers', sa.Column('credit_balance', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('customers', sa.Column('has_credit_limit', sa.Boolean(), nullable=True))
    op.add_column('customers', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('birth_date', sa.Date(), nullable=True))
    op.add_column('customers', sa.Column('last_purchase_date', sa.DateTime(), nullable=True))
    op.add_column('customers', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.add_column('customers', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('customers', sa.Column('commercial_name', sa.String(length=80), nullable=True))
    op.add_column('customers', sa.Column('otras_senas_extranjero', sa.String(length=300), nullable=True))
    op.add_column('customers', sa.Column('phone_country_code', sa.String(length=3), nullable=True))
    op.add_column('customers', sa.Column('otras_senas', sa.String(length=160), nullable=True))
    op.alter_column('customers', 'name',
        existing_type=mysql.VARCHAR(length=150),
        type_=sa.String(length=100),
        existing_nullable=False)
    op.alter_column('customers', 'address',
        existing_type=mysql.VARCHAR(length=255),
        type_=sa.String(length=200),
        existing_nullable=True)
    op.drop_index('email', table_name='customers')

    # -- economic_activities --
    op.create_index(op.f('ix_economic_activities_code'), 'economic_activities', ['code'], unique=False)

    # -- electronic_invoices --
    op.add_column('electronic_invoices', sa.Column('document_type', sa.String(length=2), nullable=False))
    op.add_column('electronic_invoices', sa.Column('xml_signed', sa.Text(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('hacienda_response', sa.Text(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('tries', sa.Integer(), nullable=False))
    op.add_column('electronic_invoices', sa.Column('last_error', sa.Text(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('sent_at', sa.DateTime(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('resolved_at', sa.DateTime(), nullable=True))
    op.alter_column('electronic_invoices', 'sale_id',
        existing_type=mysql.INTEGER(),
        nullable=False)
    op.alter_column('electronic_invoices', 'clave',
        existing_type=mysql.VARCHAR(length=50),
        nullable=True)
    op.alter_column('electronic_invoices', 'consecutivo',
        existing_type=mysql.VARCHAR(length=20),
        nullable=True)
    op.alter_column('electronic_invoices', 'hacienda_status',
        existing_type=mysql.VARCHAR(length=20),
        type_=sa.String(length=30),
        existing_nullable=True)
    op.drop_index('clave', table_name='electronic_invoices')
    op.create_index(op.f('ix_electronic_invoices_clave'), 'electronic_invoices', ['clave'], unique=True)
    op.create_index(op.f('ix_electronic_invoices_consecutivo'), 'electronic_invoices', ['consecutivo'], unique=True)
    op.create_index(op.f('ix_electronic_invoices_id'), 'electronic_invoices', ['id'], unique=False)
    op.create_index(op.f('ix_electronic_invoices_sale_id'), 'electronic_invoices', ['sale_id'], unique=False)
    op.drop_column('electronic_invoices', 'hacienda_message')
    op.drop_column('electronic_invoices', 'retry_count')
    op.drop_column('electronic_invoices', 'updated_at')
    op.drop_column('electronic_invoices', 'doc_type')
    op.drop_column('electronic_invoices', 'xml_response')
    op.drop_column('electronic_invoices', 'xml_sent')

    # -- electronic_rep_references --
    op.add_column('electronic_rep_references', sa.Column('electronic_invoice_id', sa.Integer(), nullable=False))
    op.add_column('electronic_rep_references', sa.Column('amount_applied', sa.Numeric(precision=18, scale=2), nullable=False))
    op.add_column('electronic_rep_references', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_electronic_rep_references_electronic_invoice_id'), 'electronic_rep_references', ['electronic_invoice_id'], unique=False)
    op.create_index(op.f('ix_electronic_rep_references_id'), 'electronic_rep_references', ['id'], unique=False)
    op.create_index(op.f('ix_electronic_rep_references_rep_id'), 'electronic_rep_references', ['rep_id'], unique=False)
    op.drop_constraint('electronic_rep_references_ibfk_1', 'electronic_rep_references', type_='foreignkey')
    op.create_foreign_key('fk_rep_references_rep_id', 'electronic_rep_references', 'electronic_reps', ['rep_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_rep_references_electronic_invoice_id', 'electronic_rep_references', 'electronic_invoices', ['electronic_invoice_id'], ['id'])
    op.drop_column('electronic_rep_references', 'reference_code')
    op.drop_column('electronic_rep_references', 'reason')
    op.drop_column('electronic_rep_references', 'doc_date')
    op.drop_column('electronic_rep_references', 'doc_number')
    op.drop_column('electronic_rep_references', 'doc_type')

    # -- electronic_reps --
    op.add_column('electronic_reps', sa.Column('credit_payment_id', sa.Integer(), nullable=False))
    op.add_column('electronic_reps', sa.Column('customer_id', sa.Integer(), nullable=False))
    op.add_column('electronic_reps', sa.Column('document_type', sa.String(length=2), nullable=False))
    op.add_column('electronic_reps', sa.Column('xml_signed', sa.Text(), nullable=True))
    op.add_column('electronic_reps', sa.Column('hacienda_response', sa.Text(), nullable=True))
    op.add_column('electronic_reps', sa.Column('tries', sa.Integer(), nullable=False))
    op.add_column('electronic_reps', sa.Column('last_error', sa.Text(), nullable=True))
    op.add_column('electronic_reps', sa.Column('sent_at', sa.DateTime(), nullable=True))
    op.add_column('electronic_reps', sa.Column('resolved_at', sa.DateTime(), nullable=True))
    op.alter_column('electronic_reps', 'clave',
        existing_type=mysql.VARCHAR(length=50),
        nullable=True)
    op.alter_column('electronic_reps', 'consecutivo',
        existing_type=mysql.VARCHAR(length=20),
        nullable=True)
    op.alter_column('electronic_reps', 'hacienda_status',
        existing_type=mysql.VARCHAR(length=20),
        type_=sa.String(length=30),
        existing_nullable=True)
    op.drop_index('clave', table_name='electronic_reps')
    op.create_index(op.f('ix_electronic_reps_clave'), 'electronic_reps', ['clave'], unique=True)
    op.create_index(op.f('ix_electronic_reps_consecutivo'), 'electronic_reps', ['consecutivo'], unique=True)
    op.create_index(op.f('ix_electronic_reps_credit_payment_id'), 'electronic_reps', ['credit_payment_id'], unique=False)
    op.create_index(op.f('ix_electronic_reps_customer_id'), 'electronic_reps', ['customer_id'], unique=False)
    op.create_index(op.f('ix_electronic_reps_id'), 'electronic_reps', ['id'], unique=False)
    op.create_foreign_key('fk_electronic_reps_credit_payment_id', 'electronic_reps', 'credits', ['credit_payment_id'], ['id'])
    op.create_foreign_key('fk_electronic_reps_customer_id', 'electronic_reps', 'customers', ['customer_id'], ['id'])
    op.drop_column('electronic_reps', 'updated_at')
    op.drop_column('electronic_reps', 'xml_sent')
    op.drop_column('electronic_reps', 'xml_response')

    # -- expenses --
    op.add_column('expenses', sa.Column('user_id', sa.Integer(), nullable=True))
    op.alter_column('expenses', 'amount',
        existing_type=mysql.DECIMAL(precision=10, scale=0),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False)
    op.create_foreign_key('fk_expenses_user_id', 'expenses', 'users', ['user_id'], ['id'])

    # -- inventory_movements --
    op.add_column('inventory_movements', sa.Column('type', sa.Enum('venta', 'devolucion', 'entrada', 'ajuste', 'anulacion', name='movementtype'), nullable=False))
    op.add_column('inventory_movements', sa.Column('stock_before', sa.Numeric(precision=12, scale=3), nullable=False))
    op.add_column('inventory_movements', sa.Column('stock_after', sa.Numeric(precision=12, scale=3), nullable=False))
    op.alter_column('inventory_movements', 'quantity',
        existing_type=mysql.INTEGER(),
        type_=sa.Numeric(precision=12, scale=3),
        existing_nullable=False)
    op.alter_column('inventory_movements', 'notes',
        existing_type=mysql.TEXT(),
        type_=sa.String(length=255),
        existing_nullable=True)
    op.create_index(op.f('ix_inventory_movements_id'), 'inventory_movements', ['id'], unique=False)
    op.drop_column('inventory_movements', 'movement_type')

    # -- issuer_profiles --
    op.create_index(op.f('ix_issuer_profiles_id'), 'issuer_profiles', ['id'], unique=False)

    # -- products --
    op.add_column('products', sa.Column('cabys_name', sa.String(length=500), nullable=True))
    op.add_column('products', sa.Column('category_id', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('unit_type', sa.String(length=10), nullable=False))
    op.add_column('products', sa.Column('image_path', sa.String(length=255), nullable=True))
    op.add_column('products', sa.Column('is_pos_favorite', sa.Boolean(), nullable=True))
    op.add_column('products', sa.Column('registro_fiscal_8707', sa.String(length=12), nullable=True))
    op.add_column('products', sa.Column('tax_tarifa_code_override', sa.String(length=2), nullable=True))
    op.add_column('products', sa.Column('partida_arancelaria', sa.String(length=12), nullable=True))
    op.add_column('products', sa.Column('impuesto_code', sa.String(length=2), nullable=True))
    op.add_column('products', sa.Column('factor_calculo_iva', sa.Numeric(precision=5, scale=4), nullable=True))
    op.add_column('products', sa.Column('tipo_transaccion', sa.String(length=2), nullable=True))
    op.add_column('products', sa.Column('numero_vin_serie', sa.String(length=17), nullable=True))
    op.add_column('products', sa.Column('registro_medicamento', sa.String(length=100), nullable=True))
    op.add_column('products', sa.Column('forma_farmaceutica', sa.String(length=3), nullable=True))
    op.add_column('products', sa.Column('iva_cobrado_fabrica', sa.String(length=2), nullable=True))
    op.add_column('products', sa.Column('discount_code_default', sa.String(length=2), nullable=True))
    op.add_column('products', sa.Column('imp_esp_impuesto_unidad', sa.Numeric(precision=18, scale=5), nullable=True))
    op.add_column('products', sa.Column('imp_esp_porcentaje', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('products', sa.Column('imp_esp_volumen_unidad_consumo', sa.Numeric(precision=12, scale=3), nullable=True))
    op.add_column('products', sa.Column('imp_esp_cantidad_unidad_medida', sa.Numeric(precision=12, scale=3), nullable=True))
    op.alter_column('products', 'barcode',
        existing_type=mysql.VARCHAR(length=50),
        type_=sa.String(length=100),
        existing_nullable=True)
    op.alter_column('products', 'description',
        existing_type=mysql.VARCHAR(length=255),
        type_=sa.String(length=500),
        existing_nullable=True)
    op.alter_column('products', 'cabys_code',
        existing_type=mysql.VARCHAR(length=20),
        type_=sa.String(length=50),
        existing_nullable=True)
    op.alter_column('products', 'tax_type',
        existing_type=mysql.VARCHAR(length=2),
        type_=sa.String(length=100),
        existing_nullable=True)
    op.alter_column('products', 'price',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        nullable=False)
    op.alter_column('products', 'stock',
        existing_type=mysql.INTEGER(),
        type_=sa.Numeric(precision=12, scale=3),
        existing_nullable=False)
    op.alter_column('products', 'min_stock',
        existing_type=mysql.INTEGER(),
        type_=sa.Numeric(precision=12, scale=3),
        existing_nullable=True)
    op.drop_index('barcode', table_name='products')
    op.drop_index('code', table_name='products')
    op.drop_index('ix_products_code', table_name='products')
    op.create_index(op.f('ix_products_code'), 'products', ['code'], unique=True)
    op.create_foreign_key('fk_products_category_id', 'products', 'categories', ['category_id'], ['id'])
    op.drop_column('products', 'category')

    # -- proforma_details --
    op.add_column('proforma_details', sa.Column('discount_percent', sa.Numeric(precision=5, scale=2), nullable=False))
    op.add_column('proforma_details', sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('proforma_details', sa.Column('tax_amount', sa.Numeric(precision=18, scale=5), nullable=True))
    op.add_column('proforma_details', sa.Column('is_common', sa.Boolean(), nullable=False))
    op.add_column('proforma_details', sa.Column('common_description', sa.String(length=200), nullable=True))
    op.alter_column('proforma_details', 'proforma_id',
        existing_type=mysql.INTEGER(),
        nullable=True)
    op.alter_column('proforma_details', 'quantity',
        existing_type=mysql.DECIMAL(precision=10, scale=2),
        type_=sa.Numeric(precision=12, scale=3),
        existing_nullable=False)
    op.alter_column('proforma_details', 'unit_price',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=5),
        existing_nullable=False)
    op.alter_column('proforma_details', 'subtotal',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=5),
        existing_nullable=False)
    op.create_index(op.f('ix_proforma_details_id'), 'proforma_details', ['id'], unique=False)
    op.drop_constraint('proforma_details_ibfk_1', 'proforma_details', type_='foreignkey')
    op.create_foreign_key('fk_proforma_details_proforma_id', 'proforma_details', 'proformas', ['proforma_id'], ['id'], ondelete='CASCADE')
    op.drop_column('proforma_details', 'description')

    # -- proformas --
    op.add_column('proformas', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('proformas', sa.Column('number', sa.String(length=20), nullable=False))
    op.add_column('proformas', sa.Column('validity_days', sa.Integer(), nullable=False))
    op.add_column('proformas', sa.Column('converted_sale_id', sa.Integer(), nullable=True))
    op.alter_column('proformas', 'total',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        nullable=False)
    op.alter_column('proformas', 'valid_until',
        existing_type=mysql.DATETIME(),
        nullable=False)
    op.create_index(op.f('ix_proformas_id'), 'proformas', ['id'], unique=False)
    op.create_index(op.f('ix_proformas_number'), 'proformas', ['number'], unique=True)
    op.create_foreign_key('fk_proformas_user_id', 'proformas', 'users', ['user_id'], ['id'])
    op.create_foreign_key('fk_proformas_converted_sale_id', 'proformas', 'sales', ['converted_sale_id'], ['id'])

    # -- purchase_credit_notes --
    op.add_column('purchase_credit_notes', sa.Column('date', sa.Date(), nullable=False))
    op.add_column('purchase_credit_notes', sa.Column('product_id', sa.Integer(), nullable=True))
    op.add_column('purchase_credit_notes', sa.Column('quantity_returned', sa.DECIMAL(precision=12, scale=3), nullable=True))
    op.add_column('purchase_credit_notes', sa.Column('stock_reverted', sa.Boolean(), nullable=False))
    op.alter_column('purchase_credit_notes', 'reason',
        existing_type=mysql.TEXT(),
        nullable=False)
    op.create_index(op.f('ix_purchase_credit_notes_id'), 'purchase_credit_notes', ['id'], unique=False)
    op.create_index(op.f('ix_purchase_credit_notes_purchase_id'), 'purchase_credit_notes', ['purchase_id'], unique=False)
    op.drop_constraint('purchase_credit_notes_ibfk_1', 'purchase_credit_notes', type_='foreignkey')
    op.create_foreign_key('fk_purchase_credit_notes_purchase_id', 'purchase_credit_notes', 'purchases', ['purchase_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_purchase_credit_notes_product_id', 'purchase_credit_notes', 'products', ['product_id'], ['id'])

    # -- purchase_details --
    op.add_column('purchase_details', sa.Column('unit_cost', sa.DECIMAL(precision=12, scale=2), nullable=False))
    op.alter_column('purchase_details', 'product_id',
        existing_type=mysql.INTEGER(),
        nullable=False)
    op.alter_column('purchase_details', 'quantity',
        existing_type=mysql.DECIMAL(precision=10, scale=2),
        type_=sa.DECIMAL(precision=12, scale=3),
        existing_nullable=False)
    op.create_index(op.f('ix_purchase_details_id'), 'purchase_details', ['id'], unique=False)
    op.drop_constraint('purchase_details_ibfk_1', 'purchase_details', type_='foreignkey')
    op.create_foreign_key('fk_purchase_details_purchase_id', 'purchase_details', 'purchases', ['purchase_id'], ['id'], ondelete='CASCADE')
    op.drop_column('purchase_details', 'unit_price')
    op.drop_column('purchase_details', 'description')

    # -- purchase_payments --
    op.add_column('purchase_payments', sa.Column('date', sa.Date(), nullable=False))
    op.add_column('purchase_payments', sa.Column('notes', sa.Text(), nullable=True))
    op.alter_column('purchase_payments', 'payment_method',
        existing_type=mysql.VARCHAR(length=50),
        nullable=False)
    op.create_index(op.f('ix_purchase_payments_id'), 'purchase_payments', ['id'], unique=False)
    op.create_index(op.f('ix_purchase_payments_purchase_id'), 'purchase_payments', ['purchase_id'], unique=False)
    op.drop_constraint('purchase_payments_ibfk_1', 'purchase_payments', type_='foreignkey')
    op.create_foreign_key('fk_purchase_payments_purchase_id', 'purchase_payments', 'purchases', ['purchase_id'], ['id'], ondelete='CASCADE')
    op.drop_column('purchase_payments', 'reference')

    # -- purchases --
    op.add_column('purchases', sa.Column('entry_date', sa.Date(), nullable=False))
    op.add_column('purchases', sa.Column('due_date', sa.Date(), nullable=False))
    op.add_column('purchases', sa.Column('amount', sa.DECIMAL(precision=12, scale=2), nullable=False))
    op.add_column('purchases', sa.Column('pdf_path', sa.String(length=255), nullable=True))
    op.add_column('purchases', sa.Column('payment_method', sa.String(length=50), nullable=True))
    op.add_column('purchases', sa.Column('paid_at', sa.Date(), nullable=True))
    op.add_column('purchases', sa.Column('received_at', sa.Date(), nullable=True))
    op.alter_column('purchases', 'invoice_number',
        existing_type=mysql.VARCHAR(length=100),
        type_=sa.String(length=50),
        nullable=False)
    op.alter_column('purchases', 'supplier_id',
        existing_type=mysql.INTEGER(),
        nullable=False)
    op.alter_column('purchases', 'status',
        existing_type=mysql.VARCHAR(length=20),
        type_=sa.Enum('pendiente', 'recibido', 'parcial', 'pagado', 'vencido', name='purchasestatus'),
        nullable=False,
        existing_server_default=sa.text("'PENDIENTE'"))
    op.create_index(op.f('ix_purchases_id'), 'purchases', ['id'], unique=False)
    op.create_unique_constraint('uq_purchases_invoice_number', 'purchases', ['invoice_number'])
    op.drop_column('purchases', 'tax_total')
    op.drop_column('purchases', 'total')

    # -- sale_details --
    op.add_column('sale_details', sa.Column('discount_percent', sa.Numeric(precision=5, scale=2), nullable=False))
    op.add_column('sale_details', sa.Column('tax_rate', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('sale_details', sa.Column('tax_amount', sa.Numeric(precision=18, scale=5), nullable=True))
    op.add_column('sale_details', sa.Column('is_common', sa.Boolean(), nullable=False))
    op.add_column('sale_details', sa.Column('common_description', sa.String(length=200), nullable=True))
    op.add_column('sale_details', sa.Column('discount_code', sa.String(length=2), nullable=True))
    op.add_column('sale_details', sa.Column('discount_code_otro', sa.String(length=100), nullable=True))
    op.add_column('sale_details', sa.Column('discount_description', sa.String(length=80), nullable=True))
    op.add_column('sale_details', sa.Column('tipo_transaccion', sa.String(length=2), nullable=True))
    op.add_column('sale_details', sa.Column('iva_cobrado_fabrica', sa.String(length=2), nullable=True))
    op.add_column('sale_details', sa.Column('numero_vin_serie', sa.String(length=17), nullable=True))
    op.add_column('sale_details', sa.Column('impuesto_code', sa.String(length=2), nullable=True))
    op.add_column('sale_details', sa.Column('factor_calculo_iva', sa.Numeric(precision=5, scale=4), nullable=True))
    op.add_column('sale_details', sa.Column('exon_tipo_doc', sa.String(length=2), nullable=True))
    op.add_column('sale_details', sa.Column('exon_tipo_doc_otro', sa.String(length=100), nullable=True))
    op.add_column('sale_details', sa.Column('exon_numero_doc', sa.String(length=40), nullable=True))
    op.add_column('sale_details', sa.Column('exon_articulo', sa.Integer(), nullable=True))
    op.add_column('sale_details', sa.Column('exon_inciso', sa.Integer(), nullable=True))
    op.add_column('sale_details', sa.Column('exon_institucion', sa.String(length=2), nullable=True))
    op.add_column('sale_details', sa.Column('exon_institucion_otro', sa.String(length=160), nullable=True))
    op.add_column('sale_details', sa.Column('exon_fecha', sa.DateTime(), nullable=True))
    op.add_column('sale_details', sa.Column('exon_tarifa', sa.Numeric(precision=5, scale=2), nullable=True))
    op.alter_column('sale_details', 'sale_id',
        existing_type=mysql.INTEGER(),
        nullable=True)
    op.alter_column('sale_details', 'product_id',
        existing_type=mysql.INTEGER(),
        nullable=True)
    op.alter_column('sale_details', 'quantity',
        existing_type=mysql.INTEGER(),
        type_=sa.Numeric(precision=12, scale=3),
        existing_nullable=False)
    op.alter_column('sale_details', 'unit_price',
        existing_type=mysql.DECIMAL(precision=18, scale=5),
        nullable=False)
    op.alter_column('sale_details', 'subtotal',
        existing_type=mysql.DECIMAL(precision=18, scale=5),
        nullable=False)
    op.drop_constraint('sale_details_ibfk_2', 'sale_details', type_='foreignkey')
    op.create_foreign_key('fk_sale_details_sale_id', 'sale_details', 'sales', ['sale_id'], ['id'], ondelete='CASCADE')

    # -- sales --
    op.add_column('sales', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('sales', sa.Column('cash_session_id', sa.Integer(), nullable=False))
    op.add_column('sales', sa.Column('condicion_venta_code', sa.String(length=2), nullable=True))
    op.add_column('sales', sa.Column('document_type', sa.String(length=2), nullable=False))
    op.add_column('sales', sa.Column('status', sa.String(length=20), nullable=False))
    op.add_column('sales', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('sales', sa.Column('updated_by', sa.Integer(), nullable=True))
    op.add_column('sales', sa.Column('credit_days', sa.Integer(), nullable=True))
    op.add_column('sales', sa.Column('moneda_code', sa.String(length=3), nullable=True))
    op.add_column('sales', sa.Column('tipo_cambio', sa.String(length=20), nullable=True))
    op.add_column('sales', sa.Column('condicion_venta_otros', sa.String(length=100), nullable=True))
    op.alter_column('sales', 'payment_method',
        existing_type=mysql.VARCHAR(length=50),
        type_=sa.String(length=20),
        existing_nullable=False)
    op.create_foreign_key('fk_sales_user_id', 'sales', 'users', ['user_id'], ['id'])
    op.create_foreign_key('fk_sales_cash_session_id', 'sales', 'cash_sessions', ['cash_session_id'], ['id'])
    op.create_foreign_key('fk_sales_updated_by', 'sales', 'users', ['updated_by'], ['id'])

    # -- supplier_products --
    op.create_index(op.f('ix_supplier_products_id'), 'supplier_products', ['id'], unique=False)

    # -- suppliers --
    op.add_column('suppliers', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('suppliers', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.add_column('suppliers', sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False))
    op.add_column('suppliers', sa.Column('contact_name', sa.String(length=120), nullable=True))
    op.add_column('suppliers', sa.Column('contact_phone', sa.String(length=30), nullable=True))
    op.add_column('suppliers', sa.Column('contact_position', sa.String(length=80), nullable=True))
    op.add_column('suppliers', sa.Column('id_type', sa.String(length=2), nullable=True))
    op.add_column('suppliers', sa.Column('id_number', sa.String(length=20), nullable=True))
    op.add_column('suppliers', sa.Column('commercial_name', sa.String(length=80), nullable=True))
    op.add_column('suppliers', sa.Column('provincia', sa.String(length=1), nullable=True))
    op.add_column('suppliers', sa.Column('canton', sa.String(length=2), nullable=True))
    op.add_column('suppliers', sa.Column('distrito', sa.String(length=2), nullable=True))
    op.add_column('suppliers', sa.Column('barrio', sa.String(length=50), nullable=True))
    op.add_column('suppliers', sa.Column('otras_senas', sa.String(length=250), nullable=True))
    op.add_column('suppliers', sa.Column('otras_senas_extranjero', sa.String(length=300), nullable=True))
    op.add_column('suppliers', sa.Column('phone_country_code', sa.String(length=3), nullable=True))
    op.add_column('suppliers', sa.Column('economic_activity_code', sa.String(length=6), nullable=True))
    op.alter_column('suppliers', 'name',
        existing_type=mysql.VARCHAR(length=150),
        type_=sa.String(length=255),
        existing_nullable=False)
    op.alter_column('suppliers', 'phone',
        existing_type=mysql.VARCHAR(length=30),
        type_=sa.String(length=50),
        existing_nullable=True)
    op.alter_column('suppliers', 'email',
        existing_type=mysql.VARCHAR(length=100),
        type_=sa.String(length=255),
        existing_nullable=True)
    op.alter_column('suppliers', 'address',
        existing_type=mysql.VARCHAR(length=255),
        type_=sa.Text(),
        existing_nullable=True)
    op.create_unique_constraint('uq_suppliers_name', 'suppliers', ['name'])


def downgrade() -> None:
    """Downgrade schema."""
    # ── suppliers ─────────────────────────────────────────────────────
    op.drop_constraint('uq_suppliers_name', 'suppliers', type_='unique')
    op.alter_column('suppliers', 'address',
        existing_type=sa.Text(),
        type_=mysql.VARCHAR(length=255),
        existing_nullable=True)
    op.alter_column('suppliers', 'email',
        existing_type=sa.String(length=255),
        type_=mysql.VARCHAR(length=100),
        existing_nullable=True)
    op.alter_column('suppliers', 'phone',
        existing_type=sa.String(length=50),
        type_=mysql.VARCHAR(length=30),
        existing_nullable=True)
    op.alter_column('suppliers', 'name',
        existing_type=sa.String(length=255),
        type_=mysql.VARCHAR(length=150),
        existing_nullable=False)
    op.drop_column('suppliers', 'economic_activity_code')
    op.drop_column('suppliers', 'phone_country_code')
    op.drop_column('suppliers', 'otras_senas_extranjero')
    op.drop_column('suppliers', 'otras_senas')
    op.drop_column('suppliers', 'barrio')
    op.drop_column('suppliers', 'distrito')
    op.drop_column('suppliers', 'canton')
    op.drop_column('suppliers', 'provincia')
    op.drop_column('suppliers', 'commercial_name')
    op.drop_column('suppliers', 'id_number')
    op.drop_column('suppliers', 'id_type')
    op.drop_column('suppliers', 'contact_position')
    op.drop_column('suppliers', 'contact_phone')
    op.drop_column('suppliers', 'contact_name')
    op.drop_column('suppliers', 'is_active')
    op.drop_column('suppliers', 'created_at')
    op.drop_column('suppliers', 'notes')

    # ── supplier_products ─────────────────────────────────────────────
    op.drop_index(op.f('ix_supplier_products_id'), table_name='supplier_products')

    # ── sales ─────────────────────────────────────────────────────────
    op.drop_constraint('fk_sales_updated_by', 'sales', type_='foreignkey')
    op.drop_constraint('fk_sales_cash_session_id', 'sales', type_='foreignkey')
    op.drop_constraint('fk_sales_user_id', 'sales', type_='foreignkey')
    op.alter_column('sales', 'payment_method',
        existing_type=sa.String(length=20),
        type_=mysql.VARCHAR(length=50),
        existing_nullable=False)
    op.drop_column('sales', 'condicion_venta_otros')
    op.drop_column('sales', 'tipo_cambio')
    op.drop_column('sales', 'moneda_code')
    op.drop_column('sales', 'credit_days')
    op.drop_column('sales', 'updated_by')
    op.drop_column('sales', 'updated_at')
    op.drop_column('sales', 'status')
    op.drop_column('sales', 'document_type')
    op.drop_column('sales', 'condicion_venta_code')
    op.drop_column('sales', 'cash_session_id')
    op.drop_column('sales', 'user_id')

    # ── sale_details ──────────────────────────────────────────────────
    op.drop_constraint('fk_sale_details_sale_id', 'sale_details', type_='foreignkey')
    op.create_foreign_key('sale_details_ibfk_2', 'sale_details', 'sales', ['sale_id'], ['id'])
    op.alter_column('sale_details', 'subtotal',
        existing_type=mysql.DECIMAL(precision=18, scale=5),
        nullable=True)
    op.alter_column('sale_details', 'unit_price',
        existing_type=mysql.DECIMAL(precision=18, scale=5),
        nullable=True)
    op.alter_column('sale_details', 'quantity',
        existing_type=sa.Numeric(precision=12, scale=3),
        type_=mysql.INTEGER(),
        existing_nullable=False)
    op.alter_column('sale_details', 'product_id',
        existing_type=mysql.INTEGER(),
        nullable=False)
    op.alter_column('sale_details', 'sale_id',
        existing_type=mysql.INTEGER(),
        nullable=False)
    op.drop_column('sale_details', 'exon_tarifa')
    op.drop_column('sale_details', 'exon_fecha')
    op.drop_column('sale_details', 'exon_institucion_otro')
    op.drop_column('sale_details', 'exon_institucion')
    op.drop_column('sale_details', 'exon_inciso')
    op.drop_column('sale_details', 'exon_articulo')
    op.drop_column('sale_details', 'exon_numero_doc')
    op.drop_column('sale_details', 'exon_tipo_doc_otro')
    op.drop_column('sale_details', 'exon_tipo_doc')
    op.drop_column('sale_details', 'factor_calculo_iva')
    op.drop_column('sale_details', 'impuesto_code')
    op.drop_column('sale_details', 'numero_vin_serie')
    op.drop_column('sale_details', 'iva_cobrado_fabrica')
    op.drop_column('sale_details', 'tipo_transaccion')
    op.drop_column('sale_details', 'discount_description')
    op.drop_column('sale_details', 'discount_code_otro')
    op.drop_column('sale_details', 'discount_code')
    op.drop_column('sale_details', 'common_description')
    op.drop_column('sale_details', 'is_common')
    op.drop_column('sale_details', 'tax_amount')
    op.drop_column('sale_details', 'tax_rate')
    op.drop_column('sale_details', 'discount_percent')

    # ── purchases ─────────────────────────────────────────────────────
    op.add_column('purchases', sa.Column('total', mysql.DECIMAL(precision=12, scale=2), nullable=False))
    op.add_column('purchases', sa.Column('tax_total', mysql.DECIMAL(precision=12, scale=2), server_default=sa.text("'0.00'"), nullable=True))
    op.drop_constraint('uq_purchases_invoice_number', 'purchases', type_='unique')
    op.drop_index(op.f('ix_purchases_id'), table_name='purchases')
    op.alter_column('purchases', 'status',
        existing_type=sa.Enum('pendiente', 'recibido', 'parcial', 'pagado', 'vencido', name='purchasestatus'),
        type_=mysql.VARCHAR(length=20),
        nullable=True,
        existing_server_default=sa.text("'PENDIENTE'"))
    op.alter_column('purchases', 'supplier_id',
        existing_type=mysql.INTEGER(),
        nullable=True)
    op.alter_column('purchases', 'invoice_number',
        existing_type=sa.String(length=50),
        type_=mysql.VARCHAR(length=100),
        nullable=True)
    op.drop_column('purchases', 'received_at')
    op.drop_column('purchases', 'paid_at')
    op.drop_column('purchases', 'payment_method')
    op.drop_column('purchases', 'pdf_path')
    op.drop_column('purchases', 'amount')
    op.drop_column('purchases', 'due_date')
    op.drop_column('purchases', 'entry_date')

    # ── purchase_payments ─────────────────────────────────────────────
    op.add_column('purchase_payments', sa.Column('reference', mysql.VARCHAR(length=100), nullable=True))
    op.drop_constraint('fk_purchase_payments_purchase_id', 'purchase_payments', type_='foreignkey')
    op.create_foreign_key('purchase_payments_ibfk_1', 'purchase_payments', 'purchases', ['purchase_id'], ['id'])
    op.drop_index(op.f('ix_purchase_payments_purchase_id'), table_name='purchase_payments')
    op.drop_index(op.f('ix_purchase_payments_id'), table_name='purchase_payments')
    op.alter_column('purchase_payments', 'payment_method',
        existing_type=mysql.VARCHAR(length=50),
        nullable=True)
    op.drop_column('purchase_payments', 'notes')
    op.drop_column('purchase_payments', 'date')

    # ── purchase_details ──────────────────────────────────────────────
    op.add_column('purchase_details', sa.Column('description', mysql.VARCHAR(length=255), nullable=True))
    op.add_column('purchase_details', sa.Column('unit_price', mysql.DECIMAL(precision=12, scale=2), nullable=False))
    op.drop_constraint('fk_purchase_details_purchase_id', 'purchase_details', type_='foreignkey')
    op.create_foreign_key('purchase_details_ibfk_1', 'purchase_details', 'purchases', ['purchase_id'], ['id'])
    op.drop_index(op.f('ix_purchase_details_id'), table_name='purchase_details')
    op.alter_column('purchase_details', 'quantity',
        existing_type=sa.DECIMAL(precision=12, scale=3),
        type_=mysql.DECIMAL(precision=10, scale=2),
        existing_nullable=False)
    op.alter_column('purchase_details', 'product_id',
        existing_type=mysql.INTEGER(),
        nullable=True)
    op.drop_column('purchase_details', 'unit_cost')

    # ── purchase_credit_notes ─────────────────────────────────────────
    op.drop_constraint('fk_purchase_credit_notes_product_id', 'purchase_credit_notes', type_='foreignkey')
    op.drop_constraint('fk_purchase_credit_notes_purchase_id', 'purchase_credit_notes', type_='foreignkey')
    op.create_foreign_key('purchase_credit_notes_ibfk_1', 'purchase_credit_notes', 'purchases', ['purchase_id'], ['id'])
    op.drop_index(op.f('ix_purchase_credit_notes_purchase_id'), table_name='purchase_credit_notes')
    op.drop_index(op.f('ix_purchase_credit_notes_id'), table_name='purchase_credit_notes')
    op.alter_column('purchase_credit_notes', 'reason',
        existing_type=mysql.TEXT(),
        nullable=True)
    op.drop_column('purchase_credit_notes', 'stock_reverted')
    op.drop_column('purchase_credit_notes', 'quantity_returned')
    op.drop_column('purchase_credit_notes', 'product_id')
    op.drop_column('purchase_credit_notes', 'date')

    # ── proformas ─────────────────────────────────────────────────────
    op.drop_constraint('fk_proformas_converted_sale_id', 'proformas', type_='foreignkey')
    op.drop_constraint('fk_proformas_user_id', 'proformas', type_='foreignkey')
    op.drop_index(op.f('ix_proformas_number'), table_name='proformas')
    op.drop_index(op.f('ix_proformas_id'), table_name='proformas')
    op.alter_column('proformas', 'valid_until',
        existing_type=mysql.DATETIME(),
        nullable=True)
    op.alter_column('proformas', 'total',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        nullable=True)
    op.drop_column('proformas', 'converted_sale_id')
    op.drop_column('proformas', 'validity_days')
    op.drop_column('proformas', 'number')
    op.drop_column('proformas', 'user_id')

    # ── proforma_details ──────────────────────────────────────────────
    op.add_column('proforma_details', sa.Column('description', mysql.VARCHAR(length=255), nullable=True))
    op.drop_constraint('fk_proforma_details_proforma_id', 'proforma_details', type_='foreignkey')
    op.create_foreign_key('proforma_details_ibfk_1', 'proforma_details', 'proformas', ['proforma_id'], ['id'])
    op.drop_index(op.f('ix_proforma_details_id'), table_name='proforma_details')
    op.alter_column('proforma_details', 'subtotal',
        existing_type=sa.Numeric(precision=18, scale=5),
        type_=mysql.DECIMAL(precision=12, scale=2),
        existing_nullable=False)
    op.alter_column('proforma_details', 'unit_price',
        existing_type=sa.Numeric(precision=18, scale=5),
        type_=mysql.DECIMAL(precision=12, scale=2),
        existing_nullable=False)
    op.alter_column('proforma_details', 'quantity',
        existing_type=sa.Numeric(precision=12, scale=3),
        type_=mysql.DECIMAL(precision=10, scale=2),
        existing_nullable=False)
    op.alter_column('proforma_details', 'proforma_id',
        existing_type=mysql.INTEGER(),
        nullable=False)
    op.drop_column('proforma_details', 'common_description')
    op.drop_column('proforma_details', 'is_common')
    op.drop_column('proforma_details', 'tax_amount')
    op.drop_column('proforma_details', 'tax_rate')
    op.drop_column('proforma_details', 'discount_percent')

    # ── products ──────────────────────────────────────────────────────
    op.add_column('products', sa.Column('category', mysql.VARCHAR(length=100), nullable=True))
    op.drop_constraint('fk_products_category_id', 'products', type_='foreignkey')
    op.drop_index(op.f('ix_products_code'), table_name='products')
    op.create_index('ix_products_code', 'products', ['code'], unique=False)
    op.create_index('code', 'products', ['code'], unique=True)
    op.create_index('barcode', 'products', ['barcode'], unique=True)
    op.alter_column('products', 'min_stock',
        existing_type=sa.Numeric(precision=12, scale=3),
        type_=mysql.INTEGER(),
        existing_nullable=True)
    op.alter_column('products', 'stock',
        existing_type=sa.Numeric(precision=12, scale=3),
        type_=mysql.INTEGER(),
        existing_nullable=False)
    op.alter_column('products', 'price',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        nullable=True)
    op.alter_column('products', 'tax_type',
        existing_type=sa.String(length=100),
        type_=mysql.VARCHAR(length=2),
        existing_nullable=True)
    op.alter_column('products', 'cabys_code',
        existing_type=sa.String(length=50),
        type_=mysql.VARCHAR(length=20),
        existing_nullable=True)
    op.alter_column('products', 'description',
        existing_type=sa.String(length=500),
        type_=mysql.VARCHAR(length=255),
        existing_nullable=True)
    op.alter_column('products', 'barcode',
        existing_type=sa.String(length=100),
        type_=mysql.VARCHAR(length=50),
        existing_nullable=True)
    op.drop_column('products', 'imp_esp_cantidad_unidad_medida')
    op.drop_column('products', 'imp_esp_volumen_unidad_consumo')
    op.drop_column('products', 'imp_esp_porcentaje')
    op.drop_column('products', 'imp_esp_impuesto_unidad')
    op.drop_column('products', 'discount_code_default')
    op.drop_column('products', 'iva_cobrado_fabrica')
    op.drop_column('products', 'forma_farmaceutica')
    op.drop_column('products', 'registro_medicamento')
    op.drop_column('products', 'numero_vin_serie')
    op.drop_column('products', 'tipo_transaccion')
    op.drop_column('products', 'factor_calculo_iva')
    op.drop_column('products', 'impuesto_code')
    op.drop_column('products', 'partida_arancelaria')
    op.drop_column('products', 'tax_tarifa_code_override')
    op.drop_column('products', 'registro_fiscal_8707')
    op.drop_column('products', 'is_pos_favorite')
    op.drop_column('products', 'image_path')
    op.drop_column('products', 'unit_type')
    op.drop_column('products', 'category_id')
    op.drop_column('products', 'cabys_name')

    # ── issuer_profiles ───────────────────────────────────────────────
    op.drop_index(op.f('ix_issuer_profiles_id'), table_name='issuer_profiles')

    # ── inventory_movements ───────────────────────────────────────────
    op.add_column('inventory_movements', sa.Column('movement_type', mysql.VARCHAR(length=20), nullable=False))
    op.drop_index(op.f('ix_inventory_movements_id'), table_name='inventory_movements')
    op.alter_column('inventory_movements', 'notes',
        existing_type=sa.String(length=255),
        type_=mysql.TEXT(),
        existing_nullable=True)
    op.alter_column('inventory_movements', 'quantity',
        existing_type=sa.Numeric(precision=12, scale=3),
        type_=mysql.INTEGER(),
        existing_nullable=False)
    op.drop_column('inventory_movements', 'stock_after')
    op.drop_column('inventory_movements', 'stock_before')
    op.drop_column('inventory_movements', 'type')

    # ── expenses ──────────────────────────────────────────────────────
    op.drop_constraint('fk_expenses_user_id', 'expenses', type_='foreignkey')
    op.alter_column('expenses', 'amount',
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=mysql.DECIMAL(precision=10, scale=0),
        existing_nullable=False)
    op.drop_column('expenses', 'user_id')

    # ── electronic_reps ───────────────────────────────────────────────
    op.add_column('electronic_reps', sa.Column('xml_response', mysql.TEXT(), nullable=True))
    op.add_column('electronic_reps', sa.Column('xml_sent', mysql.TEXT(), nullable=True))
    op.add_column('electronic_reps', sa.Column('updated_at', mysql.DATETIME(), nullable=True))
    op.drop_constraint('fk_electronic_reps_customer_id', 'electronic_reps', type_='foreignkey')
    op.drop_constraint('fk_electronic_reps_credit_payment_id', 'electronic_reps', type_='foreignkey')
    op.drop_index(op.f('ix_electronic_reps_id'), table_name='electronic_reps')
    op.drop_index(op.f('ix_electronic_reps_customer_id'), table_name='electronic_reps')
    op.drop_index(op.f('ix_electronic_reps_credit_payment_id'), table_name='electronic_reps')
    op.drop_index(op.f('ix_electronic_reps_consecutivo'), table_name='electronic_reps')
    op.drop_index(op.f('ix_electronic_reps_clave'), table_name='electronic_reps')
    op.create_index('clave', 'electronic_reps', ['clave'], unique=True)
    op.alter_column('electronic_reps', 'hacienda_status',
        existing_type=sa.String(length=30),
        type_=mysql.VARCHAR(length=20),
        existing_nullable=True)
    op.alter_column('electronic_reps', 'consecutivo',
        existing_type=mysql.VARCHAR(length=20),
        nullable=False)
    op.alter_column('electronic_reps', 'clave',
        existing_type=mysql.VARCHAR(length=50),
        nullable=False)
    op.drop_column('electronic_reps', 'resolved_at')
    op.drop_column('electronic_reps', 'sent_at')
    op.drop_column('electronic_reps', 'last_error')
    op.drop_column('electronic_reps', 'tries')
    op.drop_column('electronic_reps', 'hacienda_response')
    op.drop_column('electronic_reps', 'xml_signed')
    op.drop_column('electronic_reps', 'document_type')
    op.drop_column('electronic_reps', 'customer_id')
    op.drop_column('electronic_reps', 'credit_payment_id')

    # ── electronic_rep_references ─────────────────────────────────────
    op.add_column('electronic_rep_references', sa.Column('doc_type', mysql.VARCHAR(length=5), nullable=True))
    op.add_column('electronic_rep_references', sa.Column('doc_number', mysql.VARCHAR(length=50), nullable=True))
    op.add_column('electronic_rep_references', sa.Column('doc_date', mysql.DATETIME(), nullable=True))
    op.add_column('electronic_rep_references', sa.Column('reason', mysql.TEXT(), nullable=True))
    op.add_column('electronic_rep_references', sa.Column('reference_code', mysql.VARCHAR(length=2), nullable=True))
    op.drop_constraint('fk_rep_references_electronic_invoice_id', 'electronic_rep_references', type_='foreignkey')
    op.drop_constraint('fk_rep_references_rep_id', 'electronic_rep_references', type_='foreignkey')
    op.create_foreign_key('electronic_rep_references_ibfk_1', 'electronic_rep_references', 'electronic_reps', ['rep_id'], ['id'])
    op.drop_index(op.f('ix_electronic_rep_references_rep_id'), table_name='electronic_rep_references')
    op.drop_index(op.f('ix_electronic_rep_references_id'), table_name='electronic_rep_references')
    op.drop_index(op.f('ix_electronic_rep_references_electronic_invoice_id'), table_name='electronic_rep_references')
    op.drop_column('electronic_rep_references', 'created_at')
    op.drop_column('electronic_rep_references', 'amount_applied')
    op.drop_column('electronic_rep_references', 'electronic_invoice_id')

    # ── electronic_invoices ───────────────────────────────────────────
    op.add_column('electronic_invoices', sa.Column('xml_sent', mysql.TEXT(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('xml_response', mysql.TEXT(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('doc_type', mysql.VARCHAR(length=5), nullable=False))
    op.add_column('electronic_invoices', sa.Column('updated_at', mysql.DATETIME(), nullable=True))
    op.add_column('electronic_invoices', sa.Column('retry_count', mysql.INTEGER(), server_default=sa.text("'0'"), autoincrement=False, nullable=False))
    op.add_column('electronic_invoices', sa.Column('hacienda_message', mysql.TEXT(), nullable=True))
    op.drop_index(op.f('ix_electronic_invoices_sale_id'), table_name='electronic_invoices')
    op.drop_index(op.f('ix_electronic_invoices_id'), table_name='electronic_invoices')
    op.drop_index(op.f('ix_electronic_invoices_consecutivo'), table_name='electronic_invoices')
    op.drop_index(op.f('ix_electronic_invoices_clave'), table_name='electronic_invoices')
    op.create_index('clave', 'electronic_invoices', ['clave'], unique=True)
    op.alter_column('electronic_invoices', 'hacienda_status',
        existing_type=sa.String(length=30),
        type_=mysql.VARCHAR(length=20),
        existing_nullable=True)
    op.alter_column('electronic_invoices', 'consecutivo',
        existing_type=mysql.VARCHAR(length=20),
        nullable=False)
    op.alter_column('electronic_invoices', 'clave',
        existing_type=mysql.VARCHAR(length=50),
        nullable=False)
    op.alter_column('electronic_invoices', 'sale_id',
        existing_type=mysql.INTEGER(),
        nullable=True)
    op.drop_column('electronic_invoices', 'resolved_at')
    op.drop_column('electronic_invoices', 'sent_at')
    op.drop_column('electronic_invoices', 'last_error')
    op.drop_column('electronic_invoices', 'tries')
    op.drop_column('electronic_invoices', 'hacienda_response')
    op.drop_column('electronic_invoices', 'xml_signed')
    op.drop_column('electronic_invoices', 'document_type')

    # ── economic_activities ───────────────────────────────────────────
    op.drop_index(op.f('ix_economic_activities_code'), table_name='economic_activities')

    # ── customers ─────────────────────────────────────────────────────
    op.create_index('email', 'customers', ['email'], unique=True)
    op.alter_column('customers', 'address',
        existing_type=sa.String(length=200),
        type_=mysql.VARCHAR(length=255),
        existing_nullable=True)
    op.alter_column('customers', 'name',
        existing_type=sa.String(length=100),
        type_=mysql.VARCHAR(length=150),
        existing_nullable=False)
    op.drop_column('customers', 'otras_senas')
    op.drop_column('customers', 'phone_country_code')
    op.drop_column('customers', 'otras_senas_extranjero')
    op.drop_column('customers', 'commercial_name')
    op.drop_column('customers', 'updated_at')
    op.drop_column('customers', 'is_active')
    op.drop_column('customers', 'last_purchase_date')
    op.drop_column('customers', 'birth_date')
    op.drop_column('customers', 'notes')
    op.drop_column('customers', 'has_credit_limit')
    op.drop_column('customers', 'credit_balance')
    op.drop_column('customers', 'customer_type')
    op.drop_column('customers', 'secondary_phone')

    # ── credit_sales: drop new FK, restore old columns, then restore old FK ──
    op.drop_constraint('fk_credit_sales_customer_id', 'credit_sales', type_='foreignkey')
    op.drop_index(op.f('ix_credit_sales_id'), table_name='credit_sales')
    op.add_column('credit_sales', sa.Column('amount', mysql.DECIMAL(precision=12, scale=2), nullable=False))
    op.add_column('credit_sales', sa.Column('credit_id', mysql.INTEGER(), autoincrement=False, nullable=False))
    op.drop_column('credit_sales', 'total_amount')
    op.drop_column('credit_sales', 'customer_id')

    # ── categories ────────────────────────────────────────────────────
    op.add_column('categories', sa.Column('color', mysql.VARCHAR(length=20), nullable=True))
    op.drop_index(op.f('ix_categories_id'), table_name='categories')
    op.alter_column('categories', 'icon',
        existing_type=sa.String(length=10),
        type_=mysql.VARCHAR(length=50),
        existing_nullable=True)
    op.drop_column('categories', 'updated_at')
    op.drop_column('categories', 'position')
    op.drop_column('categories', 'is_active')
    op.drop_column('categories', 'description')

    # ── cash_sessions ─────────────────────────────────────────────────
    op.add_column('cash_sessions', sa.Column('opened_at', mysql.DATETIME(), nullable=True))
    op.add_column('cash_sessions', sa.Column('notes', mysql.TEXT(), nullable=True))
    op.add_column('cash_sessions', sa.Column('user_id', mysql.INTEGER(), autoincrement=False, nullable=True))
    op.create_foreign_key('cash_sessions_ibfk_1', 'cash_sessions', 'users', ['user_id'], ['id'])
    op.drop_constraint('uq_cash_date_terminal', 'cash_sessions', type_='unique')
    op.drop_index(op.f('ix_cash_sessions_id'), table_name='cash_sessions')
    op.drop_index(op.f('ix_cash_sessions_date'), table_name='cash_sessions')
    op.alter_column('cash_sessions', 'status',
        existing_type=mysql.VARCHAR(length=20),
        nullable=False,
        existing_server_default=sa.text("'OPEN'"))
    op.drop_column('cash_sessions', 'created_at')
    op.drop_column('cash_sessions', 'difference')
    op.drop_column('cash_sessions', 'expected_closing')
    op.drop_column('cash_sessions', 'terminal_id')
    op.drop_column('cash_sessions', 'date')

    # ── cash_movements ────────────────────────────────────────────────
    op.add_column('cash_movements', sa.Column('session_id', mysql.INTEGER(), autoincrement=False, nullable=False))
    op.add_column('cash_movements', sa.Column('movement_type', mysql.VARCHAR(length=20), nullable=False))
    op.drop_constraint('fk_cash_movements_cash_session_id', 'cash_movements', type_='foreignkey')
    op.create_foreign_key('cash_movements_ibfk_1', 'cash_movements', 'cash_sessions', ['session_id'], ['id'])
    op.drop_index(op.f('ix_cash_movements_id'), table_name='cash_movements')
    op.alter_column('cash_movements', 'amount',
        existing_type=mysql.DECIMAL(precision=12, scale=2),
        nullable=True)
    op.drop_column('cash_movements', 'reference_id')
    op.drop_column('cash_movements', 'source')
    op.drop_column('cash_movements', 'concept')
    op.drop_column('cash_movements', 'type')
    op.drop_column('cash_movements', 'cash_session_id')

    # ── ai_config ─────────────────────────────────────────────────────
    op.alter_column('ai_config', 'temperature',
        existing_type=sa.Numeric(precision=3, scale=2),
        type_=mysql.FLOAT(),
        existing_nullable=False,
        existing_server_default=sa.text("'0.3'"))

    # ── Recreate dropped tables (order: parents first) ────────────────
    op.create_table('credit_accounts',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('customer_id', mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('total_credit', mysql.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('credit_limit', mysql.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('last_update', mysql.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name='credit_accounts_ibfk_1', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_0900_ai_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index('ix_credit_accounts_id', 'credit_accounts', ['id'], unique=False)

    op.create_table('dashboard_snapshots',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('snapshot_date', mysql.DATETIME(), nullable=False),
        sa.Column('data', mysql.TEXT(), nullable=True),
        sa.Column('created_at', mysql.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_0900_ai_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
    )

    op.create_table('credit_payments',
        sa.Column('id', mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('credit_id', mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('amount', mysql.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('payment_date', mysql.DATETIME(), nullable=False),
        sa.ForeignKeyConstraint(['credit_id'], ['credit_accounts.id'], name='credit_payments_ibfk_1', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        mysql_collate='utf8mb4_0900_ai_ci',
        mysql_default_charset='utf8mb4',
        mysql_engine='InnoDB'
    )
    op.create_index('ix_credit_payments_id', 'credit_payments', ['id'], unique=False)

    # Now restore FK from credit_sales → credit_accounts
    op.create_foreign_key('credit_sales_ibfk_1', 'credit_sales', 'credit_accounts', ['credit_id'], ['id'])

    # ── Drop new tables ───────────────────────────────────────────────
    op.drop_index(op.f('ix_credits_id'), table_name='credits')
    op.drop_table('credits')
    op.drop_index(op.f('ix_dashboard_daily_snapshots_snapshot_date'), table_name='dashboard_daily_snapshots')
    op.drop_index(op.f('ix_dashboard_daily_snapshots_id'), table_name='dashboard_daily_snapshots')
    op.drop_table('dashboard_daily_snapshots')