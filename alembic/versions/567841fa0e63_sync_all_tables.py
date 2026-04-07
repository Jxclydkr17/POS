"""FASE 2 — Sincronizar schema completo

Crea todas las tablas que faltan sin tocar las existentes.
Es seguro correr contra una BD vacía o una que ya tiene datos.

Revision ID: 567841fa0e63 (antes: f2a0_sync_all_tables)
Revises: 914b7c5478ba
Create Date: 2025-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "567841fa0e63"
down_revision: Union[str, Sequence[str], None] = "6f77e34cfe40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """Verifica si una tabla ya existe en la BD."""
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    # ── categories ──
    if not _table_exists("categories"):
        op.create_table(
            "categories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("icon", sa.String(50), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── settings ──
    if not _table_exists("settings"):
        op.create_table(
            "settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_name", sa.String(200), nullable=True),
            sa.Column("legal_name", sa.String(200), nullable=True),
            sa.Column("id_type", sa.String(20), nullable=True),
            sa.Column("id_number", sa.String(50), nullable=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("email", sa.String(200), nullable=True),
            sa.Column("address", sa.String(500), nullable=True),
            sa.Column("logo_path", sa.String(300), nullable=True),
            sa.Column("default_tax", sa.String(10), nullable=True),
            sa.Column("default_supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("rounding_enabled", sa.Boolean(), default=False),
            sa.Column("default_currency", sa.String(3), nullable=False, server_default="CRC"),
            sa.Column("exchange_rate", sa.Numeric(10, 2), nullable=False, server_default="1.00"),
            sa.Column("printer_type", sa.String(20), nullable=True),
            sa.Column("printer_ip", sa.String(45), nullable=True),
            sa.Column("printer_port", sa.Integer(), nullable=True),
            sa.Column("cabys_last_update", sa.DateTime(), nullable=True),
            sa.Column("cabys_records", sa.Integer(), default=0),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # ── cabys ──
    if not _table_exists("cabys"):
        op.create_table(
            "cabys",
            sa.Column("code", sa.String(20), primary_key=True, index=True),
            sa.Column("description", sa.String(1500), nullable=True),
            sa.Column("iva", sa.Integer(), nullable=True),
        )

    # ── issuer_profiles ──
    if not _table_exists("issuer_profiles"):
        op.create_table(
            "issuer_profiles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("legal_name", sa.String(120), nullable=False),
            sa.Column("commercial_name", sa.String(120), nullable=True),
            sa.Column("id_type", sa.String(2), nullable=False, server_default="02"),
            sa.Column("id_number", sa.String(20), nullable=False),
            sa.Column("email", sa.String(160), nullable=False),
            sa.Column("phone", sa.String(30), nullable=True),
            sa.Column("provider_system_id", sa.String(20), nullable=True),
            sa.Column("economic_activity_code", sa.String(6), nullable=True),
            sa.Column("provincia", sa.String(1), nullable=True),
            sa.Column("canton", sa.String(2), nullable=True),
            sa.Column("distrito", sa.String(2), nullable=True),
            sa.Column("barrio", sa.String(50), nullable=True),
            sa.Column("otras_senas", sa.String(250), nullable=True),
            sa.Column("branch_code", sa.String(3), nullable=False, server_default="001"),
            sa.Column("terminal_code", sa.String(5), nullable=False, server_default="00001"),
            sa.Column("enable_rep", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rep_default_condicion_venta", sa.String(2), nullable=True),
            sa.Column("rep_default_codigo_referencia", sa.String(2), nullable=True),
            sa.Column("phone_country_code", sa.String(3), nullable=True, server_default="506"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── electronic_invoices ──
    if not _table_exists("electronic_invoices"):
        op.create_table(
            "electronic_invoices",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("sale_id", sa.Integer(), sa.ForeignKey("sales.id"), nullable=True),
            sa.Column("clave", sa.String(50), unique=True, nullable=False),
            sa.Column("consecutivo", sa.String(20), nullable=False),
            sa.Column("doc_type", sa.String(5), nullable=False),
            sa.Column("xml_sent", sa.Text(), nullable=True),
            sa.Column("xml_response", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("hacienda_status", sa.String(20), nullable=True),
            sa.Column("hacienda_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # ── purchases ──
    if not _table_exists("purchases"):
        op.create_table(
            "purchases",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("invoice_number", sa.String(100), nullable=True),
            sa.Column("total", sa.Numeric(12, 2), nullable=False),
            sa.Column("tax_total", sa.Numeric(12, 2), nullable=True, server_default="0"),
            sa.Column("status", sa.String(20), nullable=True, server_default="PENDIENTE"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # ── purchase_details ──
    if not _table_exists("purchase_details"):
        op.create_table(
            "purchase_details",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("purchases.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
            sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        )

    # ── purchase_payments ──
    if not _table_exists("purchase_payments"):
        op.create_table(
            "purchase_payments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("purchases.id"), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("payment_method", sa.String(50), nullable=True),
            sa.Column("reference", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── purchase_credit_notes ──
    if not _table_exists("purchase_credit_notes"):
        op.create_table(
            "purchase_credit_notes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("purchases.id"), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── cash_sessions ──
    if not _table_exists("cash_sessions"):
        op.create_table(
            "cash_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("opening_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("closing_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
            sa.Column("opened_at", sa.DateTime(), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )

    # ── cash_movements ──
    if not _table_exists("cash_movements"):
        op.create_table(
            "cash_movements",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("cash_sessions.id"), nullable=False),
            sa.Column("movement_type", sa.String(20), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── credit_sales ──
    if not _table_exists("credit_sales"):
        op.create_table(
            "credit_sales",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("credit_id", sa.Integer(), sa.ForeignKey("credit_accounts.id"), nullable=False),
            sa.Column("sale_id", sa.Integer(), sa.ForeignKey("sales.id"), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── electronic_reps ──
    if not _table_exists("electronic_reps"):
        op.create_table(
            "electronic_reps",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("clave", sa.String(50), unique=True, nullable=False),
            sa.Column("consecutivo", sa.String(20), nullable=False),
            sa.Column("xml_sent", sa.Text(), nullable=True),
            sa.Column("xml_response", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("hacienda_status", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # ── electronic_rep_references ──
    if not _table_exists("electronic_rep_references"):
        op.create_table(
            "electronic_rep_references",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("rep_id", sa.Integer(), sa.ForeignKey("electronic_reps.id"), nullable=False),
            sa.Column("doc_type", sa.String(5), nullable=True),
            sa.Column("doc_number", sa.String(50), nullable=True),
            sa.Column("doc_date", sa.DateTime(), nullable=True),
            sa.Column("reference_code", sa.String(2), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
        )

    # ── dashboard_snapshots ──
    if not _table_exists("dashboard_snapshots"):
        op.create_table(
            "dashboard_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_date", sa.DateTime(), nullable=False),
            sa.Column("data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── inventory_movements ──
    if not _table_exists("inventory_movements"):
        op.create_table(
            "inventory_movements",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("movement_type", sa.String(20), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("reference", sa.String(100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── proformas ──
    if not _table_exists("proformas"):
        op.create_table(
            "proformas",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
            sa.Column("total", sa.Numeric(12, 2), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="VIGENTE"),
            sa.Column("valid_until", sa.DateTime(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # ── proforma_details ──
    if not _table_exists("proforma_details"):
        op.create_table(
            "proforma_details",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("proforma_id", sa.Integer(), sa.ForeignKey("proformas.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
            sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
            sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        )

    # ── settings_audit_log (FASE 1) ──
    if not _table_exists("settings_audit_log"):
        op.create_table(
            "settings_audit_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("username", sa.String(100), nullable=True),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("changes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # ── document_sequences (FASE 1) ──
    if not _table_exists("document_sequences"):
        op.create_table(
            "document_sequences",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("branch_code", sa.String(3), nullable=False, server_default="001"),
            sa.Column("terminal_code", sa.String(5), nullable=False, server_default="00001"),
            sa.Column("document_type", sa.String(2), nullable=False),
            sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("branch_code", "terminal_code", "document_type",
                                name="uq_branch_terminal_doctype"),
        )


def downgrade() -> None:
    """Downgrade: elimina solo las tablas creadas en esta migración."""
    for table in [
        "document_sequences", "settings_audit_log",
        "proforma_details", "proformas",
        "inventory_movements", "dashboard_snapshots",
        "electronic_rep_references", "electronic_reps",
        "credit_sales",
        "cash_movements", "cash_sessions",
        "purchase_credit_notes", "purchase_payments", "purchase_details", "purchases",
        "electronic_invoices", "issuer_profiles",
        "cabys", "settings", "categories",
    ]:
        if _table_exists(table):
            op.drop_table(table)