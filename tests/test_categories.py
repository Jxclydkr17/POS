# tests/test_categories.py
"""
Cobertura del módulo de categorías:
  - CRUD completo vía HTTP (router)
  - Validaciones (duplicado, 404, campos parciales)
  - Smart delete vs delete real (#10)
  - Timestamps (created_at, updated_at)
  - Auth requerida
"""

import pytest
from app.db.models.product import Product


# ============================================================
# Helpers
# ============================================================

def _create_category(client, headers, name, icon="📦"):
    """Shortcut para crear una categoría y devolver la data."""
    resp = client.post(
        "/categories/",
        json={"name": name, "icon": icon},
        headers=headers,
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["data"]


# ============================================================
# CREAR
# ============================================================

def test_create_category(test_client, auth_headers):
    data = _create_category(test_client, auth_headers, "Electrónica Test")
    assert data["name"] == "Electrónica Test"
    assert data["icon"] == "📦"
    assert data["is_active"] is True
    assert "id" in data


def test_create_category_custom_icon(test_client, auth_headers):
    data = _create_category(test_client, auth_headers, "Hogar Test", icon="🏠")
    assert data["icon"] == "🏠"


def test_create_category_duplicate(test_client, auth_headers):
    _create_category(test_client, auth_headers, "Duplicada F4")
    resp = test_client.post(
        "/categories/",
        json={"name": "Duplicada F4"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "ya existe" in resp.json()["detail"].lower()


def test_create_category_name_too_short(test_client, auth_headers):
    resp = test_client.post(
        "/categories/",
        json={"name": "X"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ============================================================
# LISTAR
# ============================================================

def test_list_categories(test_client, auth_headers):
    _create_category(test_client, auth_headers, "Listar F4")
    resp = test_client.get("/categories/", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Categorías cargadas"
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1

    item = body["data"][0]
    assert "total_products" in item
    assert "is_active" in item


# ============================================================
# OBTENER UNA
# ============================================================

def test_get_category_by_id(test_client, auth_headers):
    cat = _create_category(test_client, auth_headers, "GetById F4")
    resp = test_client.get(f"/categories/{cat['id']}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == cat["id"]
    assert data["name"] == "GetById F4"
    assert "total_products" in data


def test_get_category_not_found(test_client, auth_headers):
    resp = test_client.get("/categories/999999", headers=auth_headers)
    assert resp.status_code == 404


# ============================================================
# ACTUALIZAR (parcial)
# ============================================================

def test_update_category_name_only(test_client, auth_headers):
    cat = _create_category(test_client, auth_headers, "Antes Update F4", icon="🔧")
    resp = test_client.put(
        f"/categories/{cat['id']}",
        json={"name": "Después Update F4"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "Después Update F4"
    # icon no se envió → debe conservar el original
    assert data["icon"] == "🔧"


def test_update_category_icon_only(test_client, auth_headers):
    cat = _create_category(test_client, auth_headers, "Icon Update F4")
    resp = test_client.put(
        f"/categories/{cat['id']}",
        json={"icon": "🎮"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["icon"] == "🎮"
    assert data["name"] == "Icon Update F4"  # no cambió


def test_update_category_is_active_only(test_client, auth_headers):
    """El PUT parcial puede desactivar sin tocar nombre ni ícono."""
    cat = _create_category(test_client, auth_headers, "Active Update F4")
    resp = test_client.put(
        f"/categories/{cat['id']}",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False
    assert resp.json()["data"]["name"] == "Active Update F4"


def test_update_category_duplicate_name(test_client, auth_headers):
    _create_category(test_client, auth_headers, "Nombre A F4")
    cat_b = _create_category(test_client, auth_headers, "Nombre B F4")
    resp = test_client.put(
        f"/categories/{cat_b['id']}",
        json={"name": "Nombre A F4"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "ya existe" in resp.json()["detail"].lower()


def test_update_category_not_found(test_client, auth_headers):
    resp = test_client.put(
        "/categories/999999",
        json={"name": "Fantasma"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ============================================================
# TOGGLE
# ============================================================

def test_toggle_category(test_client, auth_headers):
    cat = _create_category(test_client, auth_headers, "Toggle F4")

    # Primera vez → desactivar
    resp = test_client.patch(f"/categories/{cat['id']}/toggle", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False

    # Segunda vez → reactivar
    resp = test_client.patch(f"/categories/{cat['id']}/toggle", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is True


def test_toggle_category_not_found(test_client, auth_headers):
    resp = test_client.patch("/categories/999999/toggle", headers=auth_headers)
    assert resp.status_code == 404


# ============================================================
# ELIMINAR — delete real (sin productos)
# ============================================================

def test_delete_category_real(test_client, auth_headers):
    cat = _create_category(test_client, auth_headers, "Eliminar Real F4")
    resp = test_client.delete(f"/categories/{cat['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert "eliminada" in resp.json()["message"].lower()

    # Verificar que ya no existe
    resp = test_client.get(f"/categories/{cat['id']}", headers=auth_headers)
    assert resp.status_code == 404


# ============================================================
# ELIMINAR — smart delete (con productos → desactiva)
# ============================================================

def test_delete_category_smart_soft(test_client, auth_headers, db_session):
    """Si la categoría tiene productos asociados, DELETE la desactiva en vez de borrarla."""
    cat = _create_category(test_client, auth_headers, "Smart Delete F4")
    cat_id = cat["id"]

    # Insertar un producto vinculado directamente en la BD
    product = Product(
        code="SMART-DEL-TEST-001",
        name="Producto Smart Delete",
        price=100.0,
        stock=1,
        category_id=cat_id,
    )
    db_session.add(product)
    db_session.commit()

    try:
        # DELETE → debería desactivar, no borrar
        resp = test_client.delete(f"/categories/{cat_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert "desactivada" in resp.json()["message"].lower()

        # La categoría sigue existiendo pero inactiva
        resp = test_client.get(f"/categories/{cat_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["is_active"] is False
    finally:
        # Limpiar el producto de prueba
        db_session.delete(product)
        db_session.commit()


def test_delete_category_not_found(test_client, auth_headers):
    resp = test_client.delete("/categories/999999", headers=auth_headers)
    assert resp.status_code == 404


# ============================================================
# TIMESTAMPS
# ============================================================

def test_category_has_timestamps(test_client, auth_headers):
    cat = _create_category(test_client, auth_headers, "Timestamps F4")
    resp = test_client.get(f"/categories/{cat['id']}", headers=auth_headers)
    data = resp.json()["data"]
    assert data.get("created_at") is not None
    assert data.get("updated_at") is not None


# ============================================================
# AUTH
# ============================================================

def test_categories_require_auth(test_client):
    resp = test_client.get("/categories/")
    assert resp.status_code in (401, 403)

    resp = test_client.post("/categories/", json={"name": "NoAuth"})
    assert resp.status_code in (401, 403)