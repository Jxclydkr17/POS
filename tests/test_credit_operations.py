# tests/test_credit_operations.py
"""
FASE 5 — Tests para operaciones de crédito.

Verifica la lógica de negocio de créditos a clientes:
- Límite de crédito respetado
- Abonos no pueden exceder el saldo
- Saldo nunca queda negativo
- Crédito duplicado rechazado

Usa DB en memoria (SQLite) para testear con modelos reales.
"""

import pytest
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models.customer import Customer
from app.db.models.sale import Sale
from app.db.models.credit import Credit
from app.db.models.credit_sale import CreditSale
from app.db.models.cash_session import CashSession
from app.services.credit_service import add_credit_sale, add_credit_payment


# ═══════════════════════════════════════════════════════════════
# Fixtures: DB en memoria aislada por test
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def db():
    """Crea una DB SQLite en memoria fresca para cada test."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def customer_with_limit(db):
    """Cliente con límite de crédito de ₡100,000."""
    c = Customer(
        id=10, name="Ferretería ABC",
        credit_balance=Decimal("0"), credit_limit=Decimal("100000"),
        has_credit_limit=True, is_active=True,
    )
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def customer_no_limit(db):
    """Cliente sin límite de crédito."""
    c = Customer(
        id=20, name="Constructor XYZ",
        credit_balance=Decimal("0"), credit_limit=Decimal("0"),
        has_credit_limit=False, is_active=True,
    )
    db.add(c)
    db.commit()
    return c


def _create_sale(db, customer_id: int, total: Decimal, sale_id: int = None) -> Sale:
    """Helper: crea una venta mínima vinculada a una CashSession."""
    # Crear cash session si no existe
    cs = db.query(CashSession).first()
    if not cs:
        from app.utils.dt import today_cr
        cs = CashSession(id=1, date=today_cr(), opening_amount=Decimal("50000"), status="open")
        db.add(cs)
        db.flush()

    s = Sale(
        id=sale_id or (db.query(Sale).count() + 100),
        customer_id=customer_id,
        total=total,
        payment_method="Crédito",
        cash_session_id=cs.id,
        status="ACTIVA",
        document_type="04",
    )
    db.add(s)
    db.commit()
    return s


# ═══════════════════════════════════════════════════════════════
# Tests: límite de crédito
# ═══════════════════════════════════════════════════════════════

class TestCreditLimits:

    def test_sale_within_limit(self, db, customer_with_limit):
        """Venta de ₡50,000 con límite de ₡100,000 — debe pasar."""
        sale = _create_sale(db, customer_with_limit.id, Decimal("50000"))
        result = add_credit_sale(db, customer_with_limit.id, sale.id)
        db.commit()
        assert result is not None
        db.refresh(customer_with_limit)
        assert customer_with_limit.credit_balance == Decimal("50000")

    def test_sale_exceeds_limit(self, db, customer_with_limit):
        """Venta de ₡150,000 con límite de ₡100,000 — debe rechazar."""
        sale = _create_sale(db, customer_with_limit.id, Decimal("150000"))
        with pytest.raises(ValueError, match="superaría su límite"):
            add_credit_sale(db, customer_with_limit.id, sale.id)

    def test_cumulative_exceeds_limit(self, db, customer_with_limit):
        """Dos ventas que juntas superan el límite."""
        sale1 = _create_sale(db, customer_with_limit.id, Decimal("60000"), sale_id=201)
        add_credit_sale(db, customer_with_limit.id, sale1.id)
        db.commit()

        sale2 = _create_sale(db, customer_with_limit.id, Decimal("60000"), sale_id=202)
        with pytest.raises(ValueError, match="superaría su límite"):
            add_credit_sale(db, customer_with_limit.id, sale2.id)

    def test_no_limit_allows_any_amount(self, db, customer_no_limit):
        """Cliente sin límite puede acumular cualquier monto."""
        sale = _create_sale(db, customer_no_limit.id, Decimal("500000"))
        result = add_credit_sale(db, customer_no_limit.id, sale.id)
        db.commit()
        assert result is not None


# ═══════════════════════════════════════════════════════════════
# Tests: abonos / pagos
# ═══════════════════════════════════════════════════════════════

class TestCreditPayments:

    def _setup_debt(self, db, customer):
        """Helper: crea una deuda de ₡50,000."""
        sale = _create_sale(db, customer.id, Decimal("50000"), sale_id=301)
        add_credit_sale(db, customer.id, sale.id)
        db.commit()
        db.refresh(customer)

    def test_partial_payment(self, db, customer_no_limit):
        """Abono de ₡20,000 sobre deuda de ₡50,000."""
        self._setup_debt(db, customer_no_limit)

        payment = add_credit_payment(db, customer_no_limit.id, Decimal("20000"))
        db.commit()
        db.refresh(customer_no_limit)

        assert customer_no_limit.credit_balance == Decimal("30000")

    def test_full_payment(self, db, customer_no_limit):
        """Pago completo de la deuda."""
        self._setup_debt(db, customer_no_limit)

        add_credit_payment(db, customer_no_limit.id, Decimal("50000"))
        db.commit()
        db.refresh(customer_no_limit)

        assert customer_no_limit.credit_balance == Decimal("0")

    def test_overpayment_rejected(self, db, customer_no_limit):
        """Abono que excede el saldo — debe rechazar."""
        self._setup_debt(db, customer_no_limit)

        with pytest.raises(ValueError, match="excede el saldo"):
            add_credit_payment(db, customer_no_limit.id, Decimal("60000"))

    def test_zero_payment_rejected(self, db, customer_no_limit):
        """Abono de ₡0 — debe rechazar."""
        self._setup_debt(db, customer_no_limit)

        with pytest.raises(ValueError, match="mayor a cero"):
            add_credit_payment(db, customer_no_limit.id, Decimal("0"))

    def test_negative_payment_rejected(self, db, customer_no_limit):
        """Abono negativo — debe rechazar."""
        self._setup_debt(db, customer_no_limit)

        with pytest.raises(ValueError, match="mayor a cero"):
            add_credit_payment(db, customer_no_limit.id, Decimal("-5000"))

    def test_balance_never_negative(self, db, customer_no_limit):
        """Verificar que el saldo nunca queda negativo tras pago exacto."""
        self._setup_debt(db, customer_no_limit)

        add_credit_payment(db, customer_no_limit.id, Decimal("50000"))
        db.commit()
        db.refresh(customer_no_limit)

        assert customer_no_limit.credit_balance >= Decimal("0")


# ═══════════════════════════════════════════════════════════════
# Tests: duplicados
# ═══════════════════════════════════════════════════════════════

class TestCreditDuplicates:

    def test_duplicate_credit_sale_rejected(self, db, customer_no_limit):
        """La misma venta no puede generar dos créditos."""
        sale = _create_sale(db, customer_no_limit.id, Decimal("30000"), sale_id=401)
        add_credit_sale(db, customer_no_limit.id, sale.id)
        db.commit()

        with pytest.raises(ValueError, match="ya tiene un crédito"):
            add_credit_sale(db, customer_no_limit.id, sale.id)