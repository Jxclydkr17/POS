# app/db/models/__init__.py
"""
═══════════════════════════════════════════════════════════════
FASE 3 — Fix 3.4: Convención de timestamps para modelos
═══════════════════════════════════════════════════════════════

Al crear un modelo nuevo, elegir el default según la siguiente regla:

  • `default=now_cr`  → Timestamps de NEGOCIO que se comparan con rangos
    de fecha visibles al usuario (ventas, caja, reportes, movimientos).
    Se usa en: Sale.created_at, CashSession, InventoryMovement.

  • `default=utcnow`  → Timestamps TÉCNICOS de auditoría, logs, tokens,
    sincronización con servicios externos (Hacienda).
    Se usa en: User, Customer, Product, Credit, ElectronicInvoice, etc.

Referencia completa: app/utils/dt.py (docstring principal).

NUNCA usar `datetime.now()` ni `datetime.utcnow()` directamente
— ambos son naive y generan ambigüedad de zona horaria.
═══════════════════════════════════════════════════════════════
"""
from .user import User
from .category import Category
from .supplier import Supplier
from .product import Product
from .customer import Customer
from .sale import Sale
from .sale_detail import SaleDetail
from .credit import Credit
from .credit_sale import CreditSale
from .purchase import Purchase
from .purchase_detail import PurchaseDetail
from .purchase_payment import PurchasePayment
from .purchase_credit_note import PurchaseCreditNote
from .expense import Expense
from .cash_session import CashSession
from .cash_movement import CashMovement
from .settings import Settings
from .cabys import Cabys
from .economic_activity import EconomicActivity
from .payment_method import PaymentMethod
from .issuer_profile import IssuerProfile
from .electronic_invoice import ElectronicInvoice
from .electronic_rep import ElectronicRep
from .electronic_rep_reference import ElectronicRepReference
from .dashboard_snapshot import DashboardSnapshot
from .inventory_movement import InventoryMovement
from .proforma import Proforma
from .proforma_detail import ProformaDetail

# ── FASE 1 FIX: Modelos que faltaban registrar ──
from .settings_audit import SettingsAuditLog
from .document_sequence import DocumentSequence
from .supplier_product import SupplierProduct

# ── FASE 2 AI: Configuración de proveedor IA ──
from .ai_config import AIConfig
# ── Configuración sensible encriptada ──
from .secure_config import SecureConfig

__all__ = [
    "User",
    "Category",
    "Supplier",
    "Product",
    "Customer",
    "Sale",
    "SaleDetail",
    "Credit",
    "CreditSale",
    "Purchase",
    "PurchaseDetail",
    "PurchasePayment",
    "PurchaseCreditNote",
    "Expense",
    "CashSession",
    "CashMovement",
    "Settings",
    "Cabys",
    "EconomicActivity",
    "PaymentMethod",
    "IssuerProfile",
    "ElectronicInvoice",
    "ElectronicRep",
    "ElectronicRepReference",
    "DashboardSnapshot",
    "InventoryMovement",
    "Proforma",
    "ProformaDetail",
    # ── FASE 1 FIX ──
    "SettingsAuditLog",
    "DocumentSequence",
    # ── Fase 1: Relación M2M proveedor↔producto ──
    "SupplierProduct",
    # ── Fase 2 AI: Config de proveedor IA ──
    "AIConfig",
    "SecureConfig"
]