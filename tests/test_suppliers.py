# tests/test_suppliers.py
"""
Cobertura del módulo de proveedores:
  - CRUD vía HTTP (router)
  - Métricas y scoring (service)
  - Helpers internos (_avg_days_between_dates, _compute_individual_score)
  - #7 Ranking por percentiles
  - #8 Búsqueda multi-campo + filtro activos
  - #9 Paginación
  - #10 Export CSV/Excel
"""

import pytest
import math
from datetime import date, timedelta

from app.services.supplier_service import (
    _avg_days_between_dates,
    _compute_individual_score,
    _apply_scores_and_ranks,
)


# ============================================================
# Helper unit tests (sin DB)
# ============================================================

class TestAvgDaysBetweenDates:
    def test_empty_list(self):
        assert _avg_days_between_dates([]) is None

    def test_single_date(self):
        assert _avg_days_between_dates([date(2024, 1, 1)]) is None

    def test_two_dates(self):
        dates = [date(2024, 1, 1), date(2024, 1, 11)]
        assert _avg_days_between_dates(dates) == 10

    def test_multiple_dates(self):
        dates = [date(2024, 1, 1), date(2024, 1, 11), date(2024, 1, 31)]
        # diffs: 10, 20 → avg = 15
        assert _avg_days_between_dates(dates) == 15

    def test_same_day(self):
        dates = [date(2024, 1, 1), date(2024, 1, 1)]
        assert _avg_days_between_dates(dates) == 0


class TestComputeIndividualScore:
    def test_no_activity(self):
        assert _compute_individual_score(0, 0, 0, 0) == 0

    def test_full_activity_no_criticals(self):
        assert _compute_individual_score(10, 0, 5, 3) == 100

    def test_all_products_critical(self):
        assert _compute_individual_score(5, 5, 3, 2) == 80

    def test_only_purchases(self):
        assert _compute_individual_score(0, 0, 5, 0) == 40


class TestApplyScoresAndRanks:
    def test_empty(self):
        assert _apply_scores_and_ranks([]) == []

    def test_sorted_descending(self):
        suppliers = [
            {"purchases_count": 1, "rotation_units": 1, "products_count": 0, "critical_products_count": 0},
            {"purchases_count": 10, "rotation_units": 10, "products_count": 0, "critical_products_count": 0},
        ]
        result = _apply_scores_and_ranks(suppliers)
        assert result[0]["supplier_score"] >= result[1]["supplier_score"]

    # #7 Percentile ranking tests
    def test_percentile_ranking_3_suppliers(self):
        suppliers = [
            {"purchases_count": 10, "rotation_units": 20, "products_count": 5, "critical_products_count": 0},
            {"purchases_count": 5, "rotation_units": 10, "products_count": 3, "critical_products_count": 1},
            {"purchases_count": 1, "rotation_units": 2, "products_count": 1, "critical_products_count": 0},
        ]
        result = _apply_scores_and_ranks(suppliers)
        assert result[0]["supplier_rank"] == "🥇 Principal"
        # Con 3 items: top10=ceil(0.3)=1, top40=ceil(1.2)=2
        assert result[1]["supplier_rank"] == "🥈 Alternativo"
        assert result[2]["supplier_rank"] == "🥉 Ocasional"

    def test_percentile_ranking_large_set(self):
        """Con 20 proveedores: top10%=2 principales, 10-40%=6 alternativos, resto ocasional."""
        suppliers = [
            {"purchases_count": 20 - i, "rotation_units": 20 - i, "products_count": 0, "critical_products_count": 0}
            for i in range(20)
        ]
        result = _apply_scores_and_ranks(suppliers)
        n = len(result)
        top10 = math.ceil(n * 0.10)  # 2
        top40 = math.ceil(n * 0.40)  # 8

        principals = [s for s in result if s["supplier_rank"] == "🥇 Principal"]
        alternos = [s for s in result if s["supplier_rank"] == "🥈 Alternativo"]
        ocasionals = [s for s in result if s["supplier_rank"] == "🥉 Ocasional"]

        assert len(principals) == top10
        assert len(alternos) == top40 - top10
        assert len(ocasionals) == n - top40

    def test_single_supplier_is_principal(self):
        suppliers = [
            {"purchases_count": 5, "rotation_units": 10, "products_count": 2, "critical_products_count": 0},
        ]
        result = _apply_scores_and_ranks(suppliers)
        assert result[0]["supplier_rank"] == "🥇 Principal"


# ============================================================
# Tests de integración HTTP (usan test_client + SQLite)
# ============================================================

SUPPLIER_PAYLOAD = {
    "name": "Proveedor Test Suppliers",
    "phone": "22334455",
    "email": "prov@test.com",
    "address": "San José, Costa Rica",
}


def test_create_supplier(test_client, auth_headers):
    resp = test_client.post("/suppliers/", json=SUPPLIER_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == SUPPLIER_PAYLOAD["name"]
    assert data["email"] == SUPPLIER_PAYLOAD["email"]
    assert "id" in data


def test_create_supplier_duplicate(test_client, auth_headers):
    payload = {**SUPPLIER_PAYLOAD, "name": "Duplicado Test F3"}
    test_client.post("/suppliers/", json=payload, headers=auth_headers)
    resp = test_client.post("/suppliers/", json=payload, headers=auth_headers)
    assert resp.status_code == 400
    assert "ya existe" in resp.json()["detail"].lower()


# ---- #9 Paginación ----
def test_list_suppliers_paginated(test_client, auth_headers):
    resp = test_client.get("/suppliers/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Respuesta paginada
    assert "items" in data
    assert "total" in data
    assert "skip" in data
    assert "limit" in data
    assert isinstance(data["items"], list)
    if data["items"]:
        item = data["items"][0]
        assert "supplier_score" in item
        assert "dependency_pct" in item


def test_list_suppliers_skip_limit(test_client, auth_headers):
    # Crear 3 proveedores
    for i in range(3):
        test_client.post(
            "/suppliers/",
            json={**SUPPLIER_PAYLOAD, "name": f"Pag Proveedor {i}"},
            headers=auth_headers,
        )
    resp = test_client.get("/suppliers/?skip=0&limit=2", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 2
    assert data["total"] >= 3


# ---- #8 Búsqueda multi-campo ----
def test_search_by_name(test_client, auth_headers):
    test_client.post(
        "/suppliers/",
        json={**SUPPLIER_PAYLOAD, "name": "Ferretería Búsqueda"},
        headers=auth_headers,
    )
    resp = test_client.get("/suppliers/?search=Búsqueda", headers=auth_headers)
    data = resp.json()
    assert data["total"] >= 1
    assert any("Búsqueda" in s["name"] for s in data["items"])


def test_search_by_email(test_client, auth_headers):
    test_client.post(
        "/suppliers/",
        json={**SUPPLIER_PAYLOAD, "name": "EmailSearch Prov", "email": "unico99@test.com"},
        headers=auth_headers,
    )
    resp = test_client.get("/suppliers/?search=unico99", headers=auth_headers)
    data = resp.json()
    assert data["total"] >= 1


def test_filter_active(test_client, auth_headers):
    resp = test_client.get("/suppliers/?is_active=true", headers=auth_headers)
    data = resp.json()
    for s in data["items"]:
        assert s["is_active"] is True


# ---- GET by ID ----
def test_get_supplier_by_id(test_client, auth_headers):
    payload = {**SUPPLIER_PAYLOAD, "name": "Proveedor GetById F3"}
    create_resp = test_client.post("/suppliers/", json=payload, headers=auth_headers)
    sid = create_resp.json()["id"]

    resp = test_client.get(f"/suppliers/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sid
    assert "supplier_score" in data
    assert "avg_days_between_purchases" in data


def test_get_supplier_not_found(test_client, auth_headers):
    resp = test_client.get("/suppliers/999999", headers=auth_headers)
    assert resp.status_code == 404


# ---- Update ----
def test_update_supplier(test_client, auth_headers):
    payload = {**SUPPLIER_PAYLOAD, "name": "Proveedor Actualizar F3"}
    create_resp = test_client.post("/suppliers/", json=payload, headers=auth_headers)
    sid = create_resp.json()["id"]

    resp = test_client.put(
        f"/suppliers/{sid}",
        json={"name": "Proveedor Actualizado F3", "phone": "99887766"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Proveedor Actualizado F3"


def test_update_supplier_not_found(test_client, auth_headers):
    resp = test_client.put("/suppliers/999999", json={"name": "Fantasma"}, headers=auth_headers)
    assert resp.status_code == 404


# ---- Toggle ----
def test_toggle_supplier(test_client, auth_headers):
    payload = {**SUPPLIER_PAYLOAD, "name": "Proveedor Toggle F3"}
    create_resp = test_client.post("/suppliers/", json=payload, headers=auth_headers)
    sid = create_resp.json()["id"]

    resp = test_client.patch(f"/suppliers/{sid}/toggle", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = test_client.patch(f"/suppliers/{sid}/toggle", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


def test_toggle_supplier_not_found(test_client, auth_headers):
    resp = test_client.patch("/suppliers/999999/toggle", headers=auth_headers)
    assert resp.status_code == 404


# ---- Delete ----
def test_delete_supplier(test_client, auth_headers):
    payload = {**SUPPLIER_PAYLOAD, "name": "Proveedor Eliminar F3"}
    create_resp = test_client.post("/suppliers/", json=payload, headers=auth_headers)
    sid = create_resp.json()["id"]

    resp = test_client.delete(f"/suppliers/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert "eliminado" in resp.json()["message"].lower()

    resp = test_client.get(f"/suppliers/{sid}", headers=auth_headers)
    assert resp.status_code == 404


def test_delete_supplier_not_found(test_client, auth_headers):
    resp = test_client.delete("/suppliers/999999", headers=auth_headers)
    assert resp.status_code == 404


# ---- #10 Export CSV ----
def test_export_csv(test_client, auth_headers):
    resp = test_client.get("/suppliers/export/csv", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    content = resp.text
    assert "Nombre" in content
    assert "Score" in content


# ---- Auth ----
def test_supplier_requires_auth(test_client):
    resp = test_client.get("/suppliers/")
    assert resp.status_code in (401, 403)
