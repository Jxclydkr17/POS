# tests/test_purchase_credit_notes.py
"""
FASE 4 — Fix 4.5: Tests críticos para notas de crédito de compras
(PurchaseCreditNote).

El foco principal es la validación del agregado introducida por Fix 3.1
(Fase 3): la suma de notas de crédito + abonos no puede exceder el total
de la compra. Antes de ese fix, cada NC se validaba individualmente contra
el total bruto, así que una compra de ₡100,000 podía recibir 3 NCs de
₡40,000 (₡120,000 totales) y el balance quedaba en ₡-20,000.

También cubre:
  - Devolución de producto: reduce stock y crea InventoryMovement.
  - Stock insuficiente para devolución → rechazado.
  - NC sin producto → no afecta inventario.
  - Sincronización de estado (parcial / pagado) tras cada NC.
  - Tolerancia de redondeo de 0.01 colones (mismo criterio que add_payment).
  - Combinación con abonos: la suma de ambos respeta el total.

Usa DB SQLite en memoria con FK deshabilitadas para crear fixtures rápido.
"""

import pytest
from decimal import Decimal
from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.db.database import Base
from app.db.models.supplier import Supplier
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.purchase_credit_note import PurchaseCreditNote
from app.db.models.product import Product
from app.db.models.inventory_movement import InventoryMovement, MovementType
from app.schemas.purchase import (
    PurchaseCreditNoteCreate,
    PurchasePaymentCreate,
)
from app.db.crud.purchase import add_credit_note, add_payment


# ═════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════

@pytest.fixture
def db():
    """BD SQLite en memoria aislada por test. FK off (igual que
    test_credit_operations.py) para no requerir cascadas para fixtures."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _no_fk(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def supplier(db):
    s = Supplier(id=1, name="Distribuidor X", is_active=True)
    db.add(s)
    db.commit()
    return s


@pytest.fixture
def purchase(db, supplier):
    """Compra base: ₡100,000, status=recibido, sin abonos ni NCs."""
    p = Purchase(
        id=1,
        invoice_number="F-001",
        supplier_id=supplier.id,
        entry_date=date(2026, 5, 1),
        due_date=date(2026, 6, 1),
        amount=Decimal("100000"),
        status=PurchaseStatus.recibido,
    )
    db.add(p)
    db.commit()
    return p


def _cn(amount, reason="test", product_id=None, qty=0):
    """Helper: construye un PurchaseCreditNoteCreate.

    Nota: anteriormente este helper forzaba `Decimal` vía
    `object.__setattr__` por un bug latente en `add_credit_note`
    (mezcla de tipos Decimal/float al sumar credit_notes en SQLite).
    El bug fue arreglado en FASE 4 — Fix 4.6 normalizando `data.amount`
    a Decimal dentro de la función. Este helper ya no necesita workaround.
    """
    return PurchaseCreditNoteCreate(
        amount=amount,
        reason=reason,
        product_id=product_id,
        quantity_returned=Decimal(str(qty)),
    )


def _pay(amount, method="Efectivo", d=None):
    """Helper: construye un PurchasePaymentCreate."""
    return PurchasePaymentCreate(
        amount=amount,
        payment_method=method,
        date=d or date(2026, 5, 5),
    )


# ═════════════════════════════════════════════════════════
# 1. Suma de NCs — el bug central que arregló Fix 3.1
# ═════════════════════════════════════════════════════════

class TestCreditNoteAggregateLimit:

    def test_single_nc_within_total(self, db, purchase):
        """NC de ₡30,000 sobre compra de ₡100,000 → pasa."""
        add_credit_note(db, purchase.id, _cn(30000, "merma"))
        db.commit()
        db.refresh(purchase)
        assert purchase.credit_notes_total == 30000.0
        assert purchase.balance == 70000.0

    def test_single_nc_exceeds_total_rejected(self, db, purchase):
        """NC de ₡150,000 sobre compra de ₡100,000 → rechaza."""
        with pytest.raises(HTTPException) as exc:
            add_credit_note(db, purchase.id, _cn(150000, "devolución total"))
        assert exc.value.status_code == 400
        assert "excede" in exc.value.detail.lower()

    def test_three_ncs_sum_exceeds_rejected(self, db, purchase):
        """
        Fix 3.1: 3 NCs de ₡40,000 c/u contra compra ₡100,000.
        Antes del fix: cada una pasaba individualmente (40k < 100k) — BUG.
        Ahora: la 3a (que llevaría el agregado a 120k > 100k) debe rechazar.
        """
        add_credit_note(db, purchase.id, _cn(40000, "1ra"))
        db.commit()
        add_credit_note(db, purchase.id, _cn(40000, "2da"))
        db.commit()

        # Estado intermedio: 2 NCs aceptadas, 80k de 100k
        db.refresh(purchase)
        assert purchase.credit_notes_total == 80000.0
        assert purchase.balance == 20000.0

        with pytest.raises(HTTPException) as exc:
            add_credit_note(db, purchase.id, _cn(40000, "3ra"))
        assert exc.value.status_code == 400
        assert "excede" in exc.value.detail.lower()

        # Verificar que la 3a NO se grabó
        db.refresh(purchase)
        assert purchase.credit_notes_total == 80000.0
        cn_count = db.query(PurchaseCreditNote).filter(
            PurchaseCreditNote.purchase_id == purchase.id
        ).count()
        assert cn_count == 2

    def test_ncs_exactly_total_marks_pagado(self, db, purchase):
        """Suma de NCs == total → balance 0, status=pagado."""
        add_credit_note(db, purchase.id, _cn(60000))
        db.commit()
        add_credit_note(db, purchase.id, _cn(40000))
        db.commit()
        db.refresh(purchase)
        assert purchase.credit_notes_total == 100000.0
        assert purchase.balance == 0.0
        assert purchase.status == PurchaseStatus.pagado

    def test_nc_plus_payment_combined_limit(self, db, purchase):
        """
        ₡30,000 de abono + ₡70,000 de NC = ₡100,000 (total). Una NC
        adicional de ₡1,000 debe rechazar porque ya no queda saldo.
        """
        add_payment(db, purchase.id, _pay(30000))
        db.commit()
        add_credit_note(db, purchase.id, _cn(70000))
        db.commit()

        db.refresh(purchase)
        assert purchase.balance == 0.0

        with pytest.raises(HTTPException) as exc:
            add_credit_note(db, purchase.id, _cn(1000))
        assert exc.value.status_code == 400

    def test_error_detail_mentions_breakdown(self, db, purchase):
        """El mensaje de error debe explicar al usuario el desglose
        (total, abonos previos, NCs previas) para diagnóstico."""
        add_credit_note(db, purchase.id, _cn(80000))
        db.commit()

        with pytest.raises(HTTPException) as exc:
            add_credit_note(db, purchase.id, _cn(50000))
        detail = exc.value.detail
        # Debe mencionar las cifras clave
        assert "100000" in detail or "100,000" in detail or "100000.00" in detail
        assert "80000" in detail or "80,000" in detail or "80000.00" in detail

    def test_rounding_tolerance_within_one_cent(self, db, purchase):
        """
        Compra exacta de ₡100,000. Una NC de ₡100,000.005 está
        técnicamente sobre el límite pero dentro de la tolerancia de
        0.01 colones → debe pasar (mismo criterio que add_payment).
        """
        # max_allowed = 100000.0, tope con tolerancia = 100000.01
        # 100000.005 < 100000.01 → pasa
        add_credit_note(db, purchase.id, _cn(100000.005))
        db.commit()
        db.refresh(purchase)
        # No falla; el agregado quedó cercano a 100000
        assert purchase.credit_notes_total >= 100000.0

    def test_rounding_just_over_tolerance_rejected(self, db, purchase):
        """NC de ₡100,000.50 sobrepasa el tope + tolerancia → rechaza."""
        with pytest.raises(HTTPException):
            add_credit_note(db, purchase.id, _cn(100000.50))


# ═════════════════════════════════════════════════════════
# 2. Devolución de producto
# ═════════════════════════════════════════════════════════

class TestCreditNoteProductReturn:

    @pytest.fixture
    def product(self, db):
        p = Product(
            id=1, code="P001", name="Tornillo 1/2\"",
            price=Decimal("100"), cost=Decimal("60"),
            stock=Decimal("50"), unit_type="Unid", is_active=True,
        )
        db.add(p)
        db.commit()
        return p

    def test_return_reduces_stock(self, db, purchase, product):
        """Devolver 10 unidades al proveedor → stock baja de 50 a 40."""
        add_credit_note(db, purchase.id, _cn(
            amount=1000, reason="defectuoso",
            product_id=product.id, qty=10,
        ))
        db.commit()
        db.refresh(product)
        assert product.stock == Decimal("40")

    def test_return_creates_inventory_movement(self, db, purchase, product):
        """Cada devolución debe dejar trazabilidad en InventoryMovement."""
        add_credit_note(db, purchase.id, _cn(
            amount=500, reason="devolución",
            product_id=product.id, qty=5,
        ))
        db.commit()
        mov = db.query(InventoryMovement).filter(
            InventoryMovement.product_id == product.id
        ).first()
        assert mov is not None
        assert mov.type == MovementType.devolucion_proveedor
        assert mov.quantity == Decimal("5")
        assert mov.stock_before == Decimal("50")
        assert mov.stock_after == Decimal("45")

    def test_return_marks_stock_reverted(self, db, purchase, product):
        """La NC con devolución debe marcar stock_reverted=True."""
        add_credit_note(db, purchase.id, _cn(
            amount=200, reason="devolución parcial",
            product_id=product.id, qty=2,
        ))
        db.commit()
        cn = db.query(PurchaseCreditNote).filter(
            PurchaseCreditNote.purchase_id == purchase.id
        ).first()
        assert cn.stock_reverted is True

    def test_return_exceeds_stock_rejected(self, db, purchase, product):
        """Devolver 100 cuando solo hay 50 en stock → rechaza, stock intacto."""
        with pytest.raises(HTTPException) as exc:
            add_credit_note(db, purchase.id, _cn(
                amount=10000, reason="x",
                product_id=product.id, qty=100,
            ))
        assert exc.value.status_code == 400
        assert "stock" in exc.value.detail.lower()

        # Stock no se modificó
        db.refresh(product)
        assert product.stock == Decimal("50")

    def test_nc_without_product_does_not_touch_stock(self, db, purchase, product):
        """NC sin product_id (ej. descuento puro) no afecta inventario."""
        add_credit_note(db, purchase.id, _cn(amount=1000, reason="descuento"))
        db.commit()

        db.refresh(product)
        assert product.stock == Decimal("50")
        mov_count = db.query(InventoryMovement).count()
        assert mov_count == 0

        # La NC misma sí se grabó, solo que no marca stock_reverted
        cn = db.query(PurchaseCreditNote).first()
        assert cn is not None
        assert cn.stock_reverted is False

    def test_product_not_found_rejected(self, db, purchase):
        """product_id apuntando a un producto inexistente → rechaza."""
        with pytest.raises(HTTPException) as exc:
            add_credit_note(db, purchase.id, _cn(
                amount=100, reason="x",
                product_id=99999, qty=1,
            ))
        assert exc.value.status_code in (400, 404)


# ═════════════════════════════════════════════════════════
# 3. Sincronización de estado tras cada NC
# ═════════════════════════════════════════════════════════

class TestStatusSync:

    def test_partial_nc_marks_parcial(self, db, purchase):
        """
        Compra recibida + NC parcial → status pasa a `parcial`
        (porque hay credit_notes_total > 0 pero balance > 0).
        """
        # Purchase nace en `recibido` (fixture).
        assert purchase.status == PurchaseStatus.recibido

        add_credit_note(db, purchase.id, _cn(30000))
        db.commit()
        db.refresh(purchase)
        assert purchase.status == PurchaseStatus.parcial

    def test_full_nc_marks_pagado_with_paid_at(self, db, purchase):
        """NC que salda toda la deuda → status=pagado, paid_at se setea."""
        assert purchase.paid_at is None

        add_credit_note(db, purchase.id, _cn(100000))
        db.commit()
        db.refresh(purchase)
        assert purchase.status == PurchaseStatus.pagado
        assert purchase.paid_at is not None

    def test_nc_complementing_partial_payment(self, db, purchase):
        """
        Abono de ₡40,000 + NC de ₡60,000 = saldado → pagado.
        Verifica que la cadena pago + NC también dispara `pagado`.
        """
        add_payment(db, purchase.id, _pay(40000))
        db.commit()
        db.refresh(purchase)
        assert purchase.balance == 60000.0

        add_credit_note(db, purchase.id, _cn(60000))
        db.commit()
        db.refresh(purchase)
        assert purchase.balance == 0.0
        assert purchase.status == PurchaseStatus.pagado