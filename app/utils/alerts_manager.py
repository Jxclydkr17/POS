# app/utils/alerts_manager.py

import requests
from ui.session_manager import session
from ui.components.toast_notifier import show_toast
from app.core.logger import logger

API_PRODUCTS = "http://127.0.0.1:8000/products"
API_SALES = "http://127.0.0.1:8000/sales"

def check_low_stock(parent):
    """Revisa si hay productos con poco stock y muestra alerta."""
    try:
        headers = {"Authorization": f"Bearer {session.get_token()}"}
        response = requests.get(API_PRODUCTS, headers=headers)
        response.raise_for_status()
        products = response.json()

        low_stock = [p for p in products if p.get("stock", 0) <= 3]
        if low_stock:
            msg = "⚠️ Productos con bajo stock:\n" + "\n".join([f"- {p['name']} ({p['stock']} unidades)" for p in low_stock])
            show_toast(msg, success=False, parent=parent)

    except requests.HTTPError as e:
        logger.error(f"Error revisando stock: {e}")
    except Exception as e:
        logger.warning(f"Error general revisando stock: {e}")


def check_sales_performance(parent):
    """Ejemplo de revisión de desempeño de ventas (dummy por ahora)."""
    try:
        headers = {"Authorization": f"Bearer {session.get_token()}"}
        response = requests.get(API_SALES, headers=headers)
        response.raise_for_status()

        sales = response.json()
        if not sales:
            show_toast("📉 No hay ventas registradas aún.", success=False, parent=parent)

    except requests.HTTPError as e:
        logger.error(f"Error revisando desempeño de ventas: {e}")
    except Exception as e:
        logger.warning(f"Error general revisando desempeño de ventas: {e}")