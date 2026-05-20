# tests/test_ui_dialogs.py
"""
FASE 4.1 — Fix 4.1: Smoke tests para los diálogos principales del POS.

Filosofía: estos tests NO verifican comportamiento exhaustivo (clicks
de mouse, validaciones, integración con backend). Solo verifican que
los diálogos:
  - se importan sin errores,
  - se instancian sin crashear,
  - tienen los widgets esperados (ej. botones de Guardar/Cancelar),
  - el título de ventana es razonable.

Para un POS donde la UI ES el producto, esto cubre el peor caso:
"un cambio en un import / un widget renombrado / un signal eliminado
rompe el diálogo y nadie se entera hasta que el cajero le da Click".

Ejecución: `pytest tests/test_ui_dialogs.py -v`
"""

import pytest


# Marker para distinguir tests UI (pueden skipearse en CI sin display)
pytestmark = pytest.mark.ui


# ───────────────────────────────────────────────────────────────
# Fixture: prevenir requests HTTP reales en TODOS los tests UI
# ───────────────────────────────────────────────────────────────
# Los diálogos llaman `api_call` durante su `__init__` para cargar
# combos (categorías, proveedores, etc.). Sin backend corriendo, cada
# llamada cuelga 15s por el timeout. Reemplazamos:
#   - `_http_session` para que devuelva respuestas vacías inmediatas.
#   - `_set_busy` para no tocar el cursor (no hay QApplication completo).
# Como esto patchea el módulo central `ui.utils.http_worker`, afecta
# a todos los diálogos sin importar qué importen ellos.
@pytest.fixture(autouse=True)
def stub_http_session(monkeypatch):
    import ui.utils.http_worker as hw

    class _FakeResp:
        status_code = 200
        ok = True
        text = '{"data": []}'
        def json(self):
            return {"data": []}
        def raise_for_status(self):
            pass

    class _FakeSession:
        def get(self, *a, **k): return _FakeResp()
        def post(self, *a, **k): return _FakeResp()
        def put(self, *a, **k): return _FakeResp()
        def delete(self, *a, **k): return _FakeResp()
        def patch(self, *a, **k): return _FakeResp()

    monkeypatch.setattr(hw, "_http_session", _FakeSession())
    # _set_busy hace processEvents — innecesario en tests. Lo desactivamos.
    monkeypatch.setattr(hw, "_set_busy", lambda busy: None)
    yield


# ───────────────────────────────────────────────────────────────
# AddProductDialog
# ───────────────────────────────────────────────────────────────
def test_add_product_dialog_construye(qt_app):
    """Smoke: el diálogo de agregar producto se construye y tiene los
    botones esperados de Guardar y Cancelar."""
    from ui.dialogs.add_product_dialog import AddProductDialog

    dlg = AddProductDialog()
    try:
        # Título por defecto
        assert "Agregar" in dlg.windowTitle() or "producto" in dlg.windowTitle().lower()

        # Botón de guardar visible y conectado
        assert hasattr(dlg, "btn_save")
        assert dlg.btn_save is not None
        assert "guard" in dlg.btn_save.text().lower()
    finally:
        dlg.close()
        dlg.deleteLater()


def test_add_product_dialog_modo_duplicar(qt_app):
    """En modo duplicado, el título cambia para indicarlo."""
    from ui.dialogs.add_product_dialog import AddProductDialog

    dlg = AddProductDialog(duplicate_mode=True)
    try:
        assert "Duplicar" in dlg.windowTitle()
    finally:
        dlg.close()
        dlg.deleteLater()


def test_add_product_dialog_initial_data_no_crashea(qt_app):
    """Pasar initial_data parcial no debe crashear."""
    from ui.dialogs.add_product_dialog import AddProductDialog

    dlg = AddProductDialog(initial_data={
        "name": "Tornillo 1/2",
        "price": 100.0,
        "cost": 50.0,
    })
    try:
        # Debería haber cargado el nombre en algún campo
        assert dlg is not None
    finally:
        dlg.close()
        dlg.deleteLater()


# ───────────────────────────────────────────────────────────────
# AddCustomerDialog
# ───────────────────────────────────────────────────────────────
def test_add_customer_dialog_construye(qt_app):
    """Smoke: agregar cliente se construye."""
    from ui.dialogs.add_customer_dialog import AddCustomerDialog

    dlg = AddCustomerDialog()
    try:
        assert "Cliente" in dlg.windowTitle() or "cliente" in dlg.windowTitle().lower()
    finally:
        dlg.close()
        dlg.deleteLater()


# ───────────────────────────────────────────────────────────────
# ConfirmSaleDialog — el diálogo más crítico (camino feliz de la venta)
# ───────────────────────────────────────────────────────────────
def test_confirm_sale_dialog_construye(qt_app):
    """Smoke: confirmar venta se construye con datos típicos."""
    from ui.dialogs.confirm_sale_dialog import ConfirmSaleDialog

    items = [
        {"name": "Tornillo", "qty": 2, "unit_price": 100.0, "subtotal": 200.0},
        {"name": "Tuerca", "qty": 4, "unit_price": 50.0, "subtotal": 200.0},
    ]
    totals = {
        "subtotal": 400.0,
        "tax": 52.0,
        "total": 452.0,
    }

    dlg = ConfirmSaleDialog(
        customer_name="Cliente General",
        payment_method="Efectivo",
        items=items,
        totals=totals,
    )
    try:
        assert "Confirmar" in dlg.windowTitle() or "venta" in dlg.windowTitle().lower()
    finally:
        dlg.close()
        dlg.deleteLater()


def test_confirm_sale_dialog_sin_items(qt_app):
    """Caso defensivo: que no crashee si por algún error llega con lista vacía."""
    from ui.dialogs.confirm_sale_dialog import ConfirmSaleDialog

    dlg = ConfirmSaleDialog(
        customer_name="X",
        payment_method="Efectivo",
        items=[],
        totals={"subtotal": 0.0, "tax": 0.0, "total": 0.0},
    )
    try:
        assert dlg is not None
    finally:
        dlg.close()
        dlg.deleteLater()


# ───────────────────────────────────────────────────────────────
# Smoke colectivo: importar todos los dialogs no debe romper
# ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("module_name", [
    "ui.dialogs.add_product_dialog",
    "ui.dialogs.edit_product_dialog",
    "ui.dialogs.add_customer_dialog",
    "ui.dialogs.edit_customer_dialog",
    "ui.dialogs.add_category_dialog",
    "ui.dialogs.edit_category_dialog",
    "ui.dialogs.add_supplier_dialog",
    "ui.dialogs.edit_supplier_dialog",
    "ui.dialogs.add_stock_dialog",
    "ui.dialogs.add_purchase_dialog",
    "ui.dialogs.edit_purchase_dialog",
    "ui.dialogs.confirm_sale_dialog",
    "ui.dialogs.sale_summary_dialog",
    "ui.dialogs.sale_ticket_dialog",
    "ui.dialogs.day_sales_dialog",
    "ui.dialogs.edit_cart_item_dialog",
    "ui.dialogs.create_proforma_dialog",
    "ui.dialogs.proforma_detail_dialog",
    "ui.dialogs.product_movements_dialog",
    "ui.dialogs.cabys_selector_dialog",
    "ui.dialogs.common_product_dialog",
    "ui.dialogs.quantity_input_dialog",
    "ui.dialogs.icon_picker_dialog",
    "ui.dialogs.user_dialog",
])
def test_dialog_module_imports(qt_app, module_name):
    """Que cada módulo de diálogo se pueda importar sin lanzar excepción."""
    import importlib
    mod = importlib.import_module(module_name)
    assert mod is not None