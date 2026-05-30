# tests/conftest.py

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app as fastapi_app
from app.db.database import Base, get_db
import app.db.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.db.models.user import User
from app.db.models.issuer_profile import IssuerProfile
from app.db.models.customer import Customer
from app.core.security import hash_password


# FASE 4.1 — Fix 4.1: registrar marker "ui" para evitar warnings de pytest
# cuando se usen tests UI con `@pytest.mark.ui` o `pytestmark = pytest.mark.ui`.
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ui: smoke tests para diálogos PySide6 (requieren QApplication offscreen)",
    )


# ---------------------------------------------------------------------------
# BD de pruebas — SQLite EN MEMORIA, aislada POR TEST.
#
# FASE 2 — Fix 2.3: Antes `db_session` era scope="session" sobre un archivo
# `test.db` compartido y el override de get_db solo hacia rollback(), que NO
# deshace lo ya commit-eado. Resultado: el estado se filtraba entre tests y
# varios fallaban (o pasaban) segun el ORDEN de ejecucion. Eso daba una
# falsa sensacion de seguridad: "290 passed" ocultaba dependencias ocultas.
#
# Ahora cada test recibe una BD totalmente nueva: create_all -> seed -> (test)
# -> drop_all. StaticPool mantiene UNA sola conexion para que la BD :memory:
# persista durante todo el test (incluido el TestClient y su threadpool).
# ---------------------------------------------------------------------------
engine = create_engine(
    "sqlite://",  # :memory:
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def _seed_baseline(db) -> None:
    """Datos minimos que produccion garantiza, replicados en cada test."""
    # Usuario admin de prueba
    db.add(
        User(
            username="testuser",
            password=hash_password("testpass123"),
            full_name="Usuario Test",
            role="admin",
            is_active=True,
        )
    )

    # Perfil de emisor valido — toda venta lo exige (id != placeholder).
    db.add(
        IssuerProfile(
            legal_name="Ferreteria de Prueba S.A.",
            commercial_name="Ferreteria Test",
            id_type="02",
            id_number="3101234567",
            email="test@ferreteria.cr",
            phone="22001234",
            branch_code="001",
            terminal_code="00001",
        )
    )

    # -- Cliente General (id=1) --
    # El backend reserva customer_id == 1 como "Cliente General" y le niega
    # credito (sale_crud.py). Lo sembramos PRIMERO para que: (a) el cliente
    # id=1 sea efectivamente el general, y (b) los clientes reales que cree
    # cada test obtengan id >= 2 y puedan operar a credito, reflejando el
    # contrato actual del backend.
    # NOTA: produccion NO siembra esta fila (bug reportado aparte). Si se
    # corrige la forma de identificar al Cliente General, ajustar aqui.
    db.add(Customer(name="Cliente General", is_general=True, is_active=True))

    db.commit()


# ---------------------------------------------------------------------------
# Session DB (aislada por test)
# ---------------------------------------------------------------------------
@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    _seed_baseline(db)
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------
@pytest.fixture
def test_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            # El ciclo de vida de la BD lo gobierna el fixture db_session.
            # Aqui solo se limpia cualquier estado pendiente no commit-eado
            # para que una request fallida no deje la sesion inutilizable
            # para la siguiente request del mismo test.
            db_session.rollback()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    with TestClient(fastapi_app) as client:
        yield client

    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------
@pytest.fixture
def auth_headers(test_client):
    response = test_client.post(
        "/users/login",
        data={"username": "testuser", "password": "testpass123"},
    )
    assert response.status_code == 200, response.json()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# FASE 4.1 — Fix 4.1: fixture para smoke tests de UI (sin cambios)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def qt_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 no disponible")

    app = QApplication.instance() or QApplication([])
    yield app
    # No llamamos app.quit() — otros tests de la misma session pueden usarlo.