# tests/conftest.py

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app as fastapi_app
from app.db.database import Base, get_db
import app.db.models
from app.db.models.user import User
from app.db.models.issuer_profile import IssuerProfile
from app.core.security import hash_password


# FASE 4.1 — Fix 4.1: registrar marker "ui" para evitar warnings de pytest
# cuando se usen tests UI con `@pytest.mark.ui` o `pytestmark = pytest.mark.ui`.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ui: smoke tests para diálogos PySide6 (requieren QApplication offscreen)"
    )

# -------------------------
# DB de pruebas (SQLite)
# -------------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# -------------------------
# Session DB
# -------------------------
@pytest.fixture(scope="session")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # 🔐 Usuario de prueba
    test_user = User(
        username="testuser",
        password=hash_password("testpass123"),
        full_name="Usuario Test",
        role="admin",
        is_active=True
    )
    db.add(test_user)

    # ── FASE 2.4 — Fix 2.4: IssuerProfile válido para tests ──
    # Antes _get_or_create_issuer auto-creaba un dummy en sandbox; ahora
    # bloquea SIEMPRE si el id es placeholder. Los tests necesitan un
    # perfil con datos reales (cualquier id ≠ "000000000").
    issuer = IssuerProfile(
        legal_name="Ferretería de Prueba S.A.",
        commercial_name="Ferretería Test",
        id_type="02",
        id_number="3101234567",  # cédula jurídica de prueba (válida formato)
        email="test@ferreteria.cr",
        phone="22001234",
        branch_code="001",
        terminal_code="00001",
    )
    db.add(issuer)
    db.commit()

    yield db

    db.close()
    Base.metadata.drop_all(bind=engine)

# -------------------------
# Test client
# -------------------------
@pytest.fixture
def test_client(db_session):
    def override_get_db():
        # Limpiar cualquier estado pendiente (ej. IntegrityError en fixture anterior)
        # antes de que el endpoint intente usar la sesión.
        db_session.rollback()
        try:
            yield db_session
        finally:
            db_session.rollback()

    # 2. Usa el alias aquí
    fastapi_app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(fastapi_app) as client:
        yield client
    
    # 3. Limpia los overrides después del test para evitar comportamientos raros
    fastapi_app.dependency_overrides.clear()
    
# -------------------------
# Auth headers
# -------------------------
@pytest.fixture
def auth_headers(test_client):
    response = test_client.post(
        "/users/login",
        data={
            "username": "testuser",
            "password": "testpass123"
        }
    )

    assert response.status_code == 200, response.json()

    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# -------------------------
# FASE 4.1 — Fix 4.1: fixture para smoke tests de UI
# -------------------------
# Crea un QApplication offscreen una sola vez por session, para que
# los tests de diálogos puedan instanciar widgets sin requerir display.
# Si PySide6 no está disponible (entorno mínimo), los tests UI se skipean.
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
    # No llamamos app.quit() — otros tests en la misma session pueden necesitarlo.