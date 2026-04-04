# tests/conftest.py

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app as fastapi_app
from app.db.database import Base, get_db
import app.db.models
from app.db.models.user import User
from app.core.security import hash_password

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
