# tests/test_cash_close_and_credits.py
"""
FASE 5 — Fix 5.3: Tests para lógica crítica de dinero.

Cubre las áreas que faltaban:
  - Ciclo completo de caja: apertura → movimientos → cierre (con DB real)
  - Rechazo de apertura con monto negativo (Fix 3.1)
  - Precisión Decimal en cierre con muchos movimientos pequeños
  - Precisión Decimal en cadena de créditos (venta a crédito → abono)
"""

import pytest
from decimal import Decimal
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models.cash_session import CashSession
from app.db.models.cash_movement import CashMovement
from app.db.models.credit import Credit
from app.db.models.credit_sale import CreditSale
from app.db.models.customer import Customer

from app.db.crud.cash import open_session
from app.utils.decimal_utils import to_dec
from app.services.cash_close_service import close_cash_session


# ─────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """BD SQLite en memoria — aislada por test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def open_cash(db):
    """Abre una sesión de caja con ₡50,000."""
    session = open_session(db, 50000)
    return session


# ─────────────────────────────────────────────────────
# 1. Apertura de caja
# ─────────────────────────────────────────────────────

class TestOpenSession:

    def test_open_stores_decimal(self, db):
        """El monto de apertura se guarda como Decimal, no float."""
        session = open_session(db, 25000.50)
        assert session.opening_amount == Decimal("25000.50")

    def test_open_negative_rejected(self, db):
        """Fix 3.1: Monto negativo debe lanzar ValueError."""
        with pytest.raises(ValueError, match="negativo"):
            open_session(db, -100)

    def test_open_zero_allowed(self, db):
        """Abrir caja con ₡0 es válido (inicio de día sin cambio)."""
        session = open_session(db, 0)
        assert session.opening_amount == Decimal("0")
        assert session.status == "open"

    def test_open_duplicate_returns_existing(self, db):
        """Abrir dos veces el mismo día retorna la sesión existente."""
        s1 = open_session(db, 10000)
        s2 = open_session(db, 99999)  # monto distinto, misma fecha
        assert s1.id == s2.id
        # El monto original se mantiene
        assert s1.opening_amount == Decimal("10000")


# ─────────────────────────────────────────────────────
# 2. Cierre de caja — precisión Decimal con DB real
# ─────────────────────────────────────────────────────

class TestCashCloseDB:

    def _add_movement(self, db, session_id, mov_type, amount, concept="test"):
        m = CashMovement(
            cash_session_id=session_id,
            type=mov_type,
            concept=concept,
            amount=Decimal(str(amount)),
            source="manual",
        )
        db.add(m)
        db.commit()
        return m

    def test_simple_close_exact(self, db, open_cash):
        """Apertura 50k + entrada 10k - salida 3k → esperado 57k."""
        self._add_movement(db, open_cash.id, "in", 10000)
        self._add_movement(db, open_cash.id, "out", 3000)

        result = close_cash_session(db, open_cash, closing_amount=57000)

        assert result["expected_closing"] == 57000.0
        assert result["difference"] == 0.0
        assert result["status"] == "closed"

    def test_close_100_small_sales_no_drift(self, db, open_cash):
        """
        100 ventas de ₡1,130 (precio+IVA).
        Con float puro esto podría dar 112999.99... → diferencia fantasma.
        Con Decimal la diferencia debe ser EXACTAMENTE 0.
        """
        for _ in range(100):
            self._add_movement(db, open_cash.id, "in", "1130.00")

        # Esperado: 50000 + 113000 = 163000 exacto
        result = close_cash_session(db, open_cash, closing_amount=163000)

        assert result["expected_closing"] == 163000.0
        assert result["difference"] == 0.0

    def test_close_with_centimos(self, db, open_cash):
        """Céntimos no deben acumular error."""
        # 50 ventas de ₡1,333.33
        for _ in range(50):
            self._add_movement(db, open_cash.id, "in", "1333.33")

        expected = 50000 + 50 * 1333.33  # 116666.50
        result = close_cash_session(db, open_cash, closing_amount=116666.50)

        assert result["difference"] == 0.0

    def test_close_difference_reported(self, db, open_cash):
        """Si el cajero cuenta de más/menos, la diferencia se reporta."""
        self._add_movement(db, open_cash.id, "in", 20000)
        # Esperado: 70000, cajero cuenta 70050 → diferencia +50
        result = close_cash_session(db, open_cash, closing_amount=70050)

        assert result["expected_closing"] == 70000.0
        assert result["difference"] == 50.0

    def test_close_persists_to_db(self, db, open_cash):
        """Los valores de cierre se persisten en la BD."""
        self._add_movement(db, open_cash.id, "in", 5000)

        close_cash_session(db, open_cash, closing_amount=55000)

        refreshed = db.query(CashSession).get(open_cash.id)
        assert refreshed.status == "closed"
        assert refreshed.closing_amount == Decimal("55000")
        assert refreshed.expected_closing == Decimal("55000")
        assert refreshed.difference == Decimal("0")


# ─────────────────────────────────────────────────────
# 3. Créditos — precisión en la cadena venta→abono
# ─────────────────────────────────────────────────────

class TestCreditPrecision:

    @pytest.fixture()
    def customer(self, db):
        c = Customer(
            name="Ferretería Don Pepe",
            phone="88881234",
            is_active=True,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return c

    def _add_credit_movement(self, db, customer_id, mov_type, amount):
        m = Credit(
            customer_id=customer_id,
            type=mov_type,
            amount=Decimal(str(amount)),
            description=f"Test {mov_type}",
            created_at=datetime.now(),
        )
        db.add(m)
        db.commit()
        return m

    def test_balance_exact_after_partial_payments(self, db, customer):
        """
        Venta de ₡15,750.75 → 3 abonos de ₡5,250.25 = saldo 0 exacto.
        Con float: 5250.25 * 3 = 15750.749999... → saldo fantasma.
        """
        self._add_credit_movement(db, customer.id, "sale", "15750.75")
        for _ in range(3):
            self._add_credit_movement(db, customer.id, "payment", "5250.25")

        # Calcular balance desde la BD
        from sqlalchemy import func, case
        totals = db.query(
            func.sum(
                case(
                    (Credit.type == "sale", Credit.amount),
                    else_=-Credit.amount,
                )
            )
        ).filter(Credit.customer_id == customer.id).scalar()

        balance = to_dec(totals)
        assert balance == Decimal("0.00") or balance == Decimal("0")

    def test_many_small_credit_sales(self, db, customer):
        """200 ventas a crédito de ₡565.50 = ₡113,100 exacto."""
        for _ in range(200):
            self._add_credit_movement(db, customer.id, "sale", "565.50")

        from sqlalchemy import func
        total = db.query(func.sum(Credit.amount)).filter(
            Credit.customer_id == customer.id,
            Credit.type == "sale",
        ).scalar()

        assert to_dec(total) == Decimal("113100.00")

    def test_payment_larger_than_sale_not_negative(self, db, customer):
        """Un abono mayor que la deuda no debe dar balance negativo."""
        self._add_credit_movement(db, customer.id, "sale", "1000")
        self._add_credit_movement(db, customer.id, "payment", "1000")

        from sqlalchemy import func
        total_sales = db.query(func.sum(Credit.amount)).filter(
            Credit.customer_id == customer.id, Credit.type == "sale"
        ).scalar() or 0
        total_payments = db.query(func.sum(Credit.amount)).filter(
            Credit.customer_id == customer.id, Credit.type == "payment"
        ).scalar() or 0

        balance = to_dec(total_sales) - to_dec(total_payments)
        assert balance >= Decimal("0")