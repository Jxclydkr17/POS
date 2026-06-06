"""
tests/test_password_recovery.py — Flujo de recuperación de contraseña del admin.

Cubre el flujo "¿Olvidó su contraseña?" (estilo Google) de extremo a extremo:
  - /users/recover-password/request   (cédula + correo → código por correo)
  - /users/recover-password/verify    (código → reset_token)
  - /users/recover-password/reset     (reset_token + nueva contraseña)

El envío de correo (yagmail/SMTP) se monkeypatchea para capturar el código de
6 dígitos sin enviar nada real, y para no depender de credenciales de correo
en el entorno de pruebas.

También verifica que /users/setup capture y persista cédula + correo.
"""
import pytest

import app.utils.email_utils as email_utils
import app.routers.users as users_mod
from app.db.models.user import User
from app.core.security import hash_password


# ──────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────────
@pytest.fixture
def captured_codes(monkeypatch):
    """Captura el código de recuperación en vez de enviarlo por correo."""
    box = {}

    def _fake_send(recipient, code, business_name=None):
        box["recipient"] = recipient
        box["code"] = code
        return True

    monkeypatch.setattr(email_utils, "send_password_recovery_code", _fake_send)
    return box


@pytest.fixture(autouse=True)
def _clear_recovery_state():
    """Limpia el almacén en memoria de códigos entre tests.

    También resetea los buckets del rate limiter global (estado de módulo
    que de otro modo se filtra entre tests y provoca 429 espurios).
    """
    import app.core.rate_limiter as rl

    with users_mod._recovery_lock:
        users_mod._recovery_codes.clear()
    with rl._lock:
        rl._buckets.clear()
    yield
    with users_mod._recovery_lock:
        users_mod._recovery_codes.clear()
    with rl._lock:
        rl._buckets.clear()


@pytest.fixture
def admin_with_identity(db_session):
    """Dota al admin de prueba (testuser) de cédula y correo."""
    user = db_session.query(User).filter(User.username == "testuser").first()
    user.cedula = "1-1234-5678"
    user.correo = "jackob@ferreteria.cr"
    db_session.commit()
    return user


CEDULA = "1-1234-5678"
CORREO = "jackob@ferreteria.cr"


# ──────────────────────────────────────────────────────────────────
# Flujo feliz completo
# ──────────────────────────────────────────────────────────────────
def test_full_recovery_flow(test_client, admin_with_identity, captured_codes):
    # Paso 1: solicitar código
    r = test_client.post(
        "/users/recover-password/request",
        json={"cedula": CEDULA, "correo": CORREO},
    )
    assert r.status_code == 200
    body = r.json()
    assert "correo_masked" in body
    code = captured_codes["code"]
    assert code.isdigit() and len(code) == 6

    # Paso 2: verificar código
    r = test_client.post(
        "/users/recover-password/verify",
        json={"cedula": CEDULA, "correo": CORREO, "code": code},
    )
    assert r.status_code == 200
    reset_token = r.json()["reset_token"]
    assert reset_token

    # Paso 3: resetear contraseña
    r = test_client.post(
        "/users/recover-password/reset",
        json={"reset_token": reset_token, "new_password": "claveNueva456"},
    )
    assert r.status_code == 200

    # La nueva contraseña funciona; la vieja ya no.
    r = test_client.post("/users/login", data={"username": "testuser", "password": "claveNueva456"})
    assert r.status_code == 200
    r = test_client.post("/users/login", data={"username": "testuser", "password": "testpass123"})
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────
# Validación de identidad ("Mmm, esos no son")
# ──────────────────────────────────────────────────────────────────
def test_wrong_identity_friendly_error(test_client, admin_with_identity, captured_codes):
    r = test_client.post(
        "/users/recover-password/request",
        json={"cedula": "9-9999-9999", "correo": CORREO},
    )
    assert r.status_code == 400
    assert "Mmm" in r.json()["detail"]
    assert "code" not in captured_codes  # no se generó ni envió código


def test_cedula_normalization(test_client, admin_with_identity, captured_codes):
    """La cédula coincide aunque se escriba sin guiones."""
    r = test_client.post(
        "/users/recover-password/request",
        json={"cedula": "112345678", "correo": "JACKOB@Ferreteria.CR"},
    )
    assert r.status_code == 200


def test_admin_without_identity_cannot_recover(test_client, captured_codes):
    """Un admin sin cédula/correo no puede recuperar (datos no coinciden)."""
    r = test_client.post(
        "/users/recover-password/request",
        json={"cedula": CEDULA, "correo": CORREO},
    )
    assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────
# Código: incorrecto, un solo uso, salto de pasos
# ──────────────────────────────────────────────────────────────────
def test_wrong_code_rejected(test_client, admin_with_identity, captured_codes):
    test_client.post("/users/recover-password/request",
                     json={"cedula": CEDULA, "correo": CORREO})
    r = test_client.post(
        "/users/recover-password/verify",
        json={"cedula": CEDULA, "correo": CORREO, "code": "000000"},
    )
    assert r.status_code == 400


def test_code_is_single_use(test_client, admin_with_identity, captured_codes):
    test_client.post("/users/recover-password/request",
                     json={"cedula": CEDULA, "correo": CORREO})
    code = captured_codes["code"]
    # Primer uso: OK
    r = test_client.post("/users/recover-password/verify",
                         json={"cedula": CEDULA, "correo": CORREO, "code": code})
    assert r.status_code == 200
    # Segundo uso del mismo código: rechazado
    r = test_client.post("/users/recover-password/verify",
                         json={"cedula": CEDULA, "correo": CORREO, "code": code})
    assert r.status_code == 400


def test_reset_requires_valid_token(test_client, admin_with_identity, captured_codes):
    """No se puede resetear sin un reset_token válido (no se salta la verificación)."""
    r = test_client.post(
        "/users/recover-password/reset",
        json={"reset_token": "token.basura.invalido", "new_password": "loquesea123"},
    )
    assert r.status_code == 400


def test_too_many_wrong_codes_invalidates(test_client, admin_with_identity, captured_codes):
    test_client.post("/users/recover-password/request",
                     json={"cedula": CEDULA, "correo": CORREO})
    code = captured_codes["code"]
    # Agotar los intentos con códigos equivocados.
    for _ in range(users_mod.RECOVERY_MAX_VERIFY_ATTEMPTS):
        test_client.post("/users/recover-password/verify",
                         json={"cedula": CEDULA, "correo": CORREO, "code": "111111"})
    # Aun con el código correcto, ya fue invalidado.
    r = test_client.post("/users/recover-password/verify",
                         json={"cedula": CEDULA, "correo": CORREO, "code": code})
    assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────
# Setup inicial captura cédula + correo
# ──────────────────────────────────────────────────────────────────
def test_setup_persists_cedula_correo(test_client, db_session):
    # Vaciar usuarios para que /setup esté permitido.
    db_session.query(User).delete()
    db_session.commit()

    r = test_client.post(
        "/users/setup",
        json={
            "username": "admin",
            "password": "claveAdmin123",
            "cedula": "2-0987-6543",
            "correo": "DUENO@Negocio.CR",
            "full_name": "Dueño",
        },
    )
    assert r.status_code == 200

    admin = db_session.query(User).filter(User.username == "admin").first()
    assert admin.cedula == "2-0987-6543"
    assert admin.correo == "dueno@negocio.cr"  # normalizado a minúsculas


def test_setup_requires_email(test_client, db_session):
    db_session.query(User).delete()
    db_session.commit()
    r = test_client.post(
        "/users/setup",
        json={"username": "admin", "password": "claveAdmin123", "cedula": "2-0987-6543"},
    )
    assert r.status_code == 422  # correo faltante → validación pydantic