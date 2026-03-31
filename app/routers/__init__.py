from .analytics import router as analytics_router
from .cabys import router as cabys_router
from .cash import router as cash_router
from .categories import router as categories_router
from .credits import router as credits_router
from .customers import router as customers_router
from .expenses import router as expenses_router
from .financial_reports import router as financial_reports_router
from .products import router as products_router
from .purchases import router as purchases_router
from .reports_extended import router as reports_extended_router
from .sales import router as sales_router
from .settings import router as settings_router
from .suppliers import router as suppliers_router
from .users import router as users_router
from .einvoice import router as einvoice_router
from .dashboard import router as dashboard_router
from .proformas import router as proformas_router

__all__ = [
    "analytics_router",
    "cabys_router",
    "cash_router",
    "categories_router",
    "credits_router",
    "customers_router",
    "expenses_router",
    "financial_reports_router",
    "products_router",
    "purchases_router",
    "reports_extended_router",
    "sales_router",
    "settings_router",
    "suppliers_router",
    "users_router",
    "einvoice_router",
    "dashboard_router",
    "proformas_router",
]