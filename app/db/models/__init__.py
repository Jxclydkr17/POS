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
]