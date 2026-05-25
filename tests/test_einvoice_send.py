# tests/test_einvoice_send.py
"""
FASE 4 — Fix 4.5: Tests críticos para el flujo de envío de comprobantes
electrónicos a Hacienda CR.

Cubre dos niveles:

1. HaciendaClient (unit tests con `requests` mockeado):
   - Validación de config (env, user, password).
   - Autenticación OAuth2: cache, refresh, errores.
   - send_document: 202 OK, retry en 401, error 400, error de red.
   - check_status: estados ACEPTADO / NO_ENCONTRADO.

2. send_einvoice_to_hacienda (integration tests con BD SQLite + cliente mockeado):
   - Camino feliz: XML_READY → SENT (con sent_at, tries++, last_error limpio).
   - Error de red → cola offline (status QUEUED).
   - Error de Hacienda (no red) → SEND_ERROR (last_error guardado).
   - HaciendaConfigError → SEND_ERROR.
   - Validaciones previas (xml_signed, clave, status, existencia).
   - Reintento desde SEND_ERROR limpia el last_error.

Sin red ni credenciales reales — todo mockeado.
"""

import time
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.einvoice.hacienda_client import (
    HaciendaClient,
    HaciendaAuthError,
    HaciendaSendError,
    HaciendaConfigError,
)


# ═══════════════════════════════════════════════════════════
# Helpers de mocks HTTP
# ═══════════════════════════════════════════════════════════

def _token_resp(token: str = "tok-x", expires_in: int = 300) -> MagicMock:
    """Respuesta exitosa del IdP (OAuth2)."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"access_token": token, "expires_in": expires_in}
    return r


def _send_resp(status_code: int = 202, body: dict | None = None) -> MagicMock:
    """Respuesta del API /recepcion."""
    r = MagicMock()
    r.status_code = status_code
    r.text = "mock response body"
    if body is not None:
        r.json.return_value = body
    else:
        r.json.side_effect = ValueError("no JSON body")
    return r


def _seed_token(client: HaciendaClient, token: str = "cached-tok") -> None:
    """Inyecta un token válido para saltar la llamada OAuth en tests de envío."""
    client._access_token = token
    client._token_expires_at = time.time() + 3600


# ═══════════════════════════════════════════════════════════
# 1. HaciendaClient — configuración
# ═══════════════════════════════════════════════════════════

class TestHaciendaClientConfig:

    def test_invalid_env_rejected(self):
        with pytest.raises(HaciendaConfigError, match="Ambiente"):
            HaciendaClient(env="prod", user="x", password="y")

    def test_empty_user_rejected(self):
        with pytest.raises(HaciendaConfigError, match="requeridos"):
            HaciendaClient(env="sandbox", user="", password="y")

    def test_empty_password_rejected(self):
        with pytest.raises(HaciendaConfigError, match="requeridos"):
            HaciendaClient(env="sandbox", user="x", password="")

    def test_valid_config_does_not_request_token(self):
        """El constructor no debe hacer red — el token se pide on-demand."""
        c = HaciendaClient(env="sandbox", user="cpf-test", password="pass")
        assert c._access_token is None
        assert c._token_expires_at == 0


# ═══════════════════════════════════════════════════════════
# 2. HaciendaClient — autenticación OAuth2
# ═══════════════════════════════════════════════════════════

class TestHaciendaClientAuth:

    def test_token_requested_on_first_use(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        with patch("app.einvoice.hacienda_client.requests.post") as mp:
            mp.return_value = _token_resp("tok-1")
            tok = c._get_token()
            assert tok == "tok-1"
            assert mp.call_count == 1
            # Body de OAuth2 ROPC
            assert mp.call_args.kwargs["data"]["username"] == "u"
            assert mp.call_args.kwargs["data"]["password"] == "p"
            assert mp.call_args.kwargs["data"]["grant_type"] == "password"

    def test_token_cached_between_calls(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        with patch("app.einvoice.hacienda_client.requests.post") as mp:
            mp.return_value = _token_resp("tok-1", expires_in=600)
            c._get_token()
            c._get_token()
            c._get_token()
            # Solo se solicitó UNA vez (cache funciona)
            assert mp.call_count == 1

    def test_token_renewed_after_invalidate(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        with patch("app.einvoice.hacienda_client.requests.post") as mp:
            mp.return_value = _token_resp("tok-1")
            assert c._get_token() == "tok-1"
            c.invalidate_token()
            mp.return_value = _token_resp("tok-2")
            assert c._get_token() == "tok-2"
            assert mp.call_count == 2

    def test_auth_401_raises_credentials_error(self):
        c = HaciendaClient(env="sandbox", user="u", password="bad")
        bad = MagicMock()
        bad.status_code = 401
        bad.text = "invalid_grant"
        with patch("app.einvoice.hacienda_client.requests.post", return_value=bad):
            with pytest.raises(HaciendaAuthError, match="Credenciales"):
                c._get_token()

    def test_auth_connection_error(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            side_effect=requests.ConnectionError("DNS"),
        ):
            with pytest.raises(HaciendaAuthError, match="No se pudo conectar"):
                c._get_token()

    def test_auth_timeout(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            side_effect=requests.Timeout(),
        ):
            with pytest.raises(HaciendaAuthError, match="Timeout"):
                c._get_token()

    def test_auth_no_access_token_in_response(self):
        """El IdP responde 200 pero sin access_token → error."""
        c = HaciendaClient(env="sandbox", user="u", password="p")
        weird = MagicMock()
        weird.status_code = 200
        weird.json.return_value = {"expires_in": 300}  # falta access_token
        with patch("app.einvoice.hacienda_client.requests.post", return_value=weird):
            with pytest.raises(HaciendaAuthError, match="access_token"):
                c._get_token()


# ═══════════════════════════════════════════════════════════
# 3. HaciendaClient — envío de comprobantes (send_document)
# ═══════════════════════════════════════════════════════════

class TestHaciendaClientSend:

    def test_send_success_202_returns_recibido(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            return_value=_send_resp(202, {"x-Identificador": "abc"}),
        ):
            result = c.send_document(
                clave="50601012600310123456700100001010000000001123456789",
                fecha="2026-05-23T14:30:00-06:00",
                emisor_tipo="02",
                emisor_numero="3101234567",
                xml_base64="PHhtbC8+",
            )
        assert result["status"] == "RECIBIDO"
        assert result["http_status"] == 202

    def test_send_includes_receptor_when_provided(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            return_value=_send_resp(202, {}),
        ) as mp:
            c.send_document(
                clave="x", fecha="x", emisor_tipo="02",
                emisor_numero="3101234567",
                receptor_tipo="01", receptor_numero="123456789",
                xml_base64="PHhtbC8+",
            )
        body = mp.call_args.kwargs["json"]
        assert body["receptor"]["tipoIdentificacion"] == "01"
        assert body["receptor"]["numeroIdentificacion"] == "123456789"
        assert body["emisor"]["tipoIdentificacion"] == "02"
        assert body["comprobanteXml"] == "PHhtbC8+"

    def test_send_omits_receptor_when_missing(self):
        """Para tiquete electrónico (TE) el receptor es opcional."""
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            return_value=_send_resp(202, {}),
        ) as mp:
            c.send_document(
                clave="x", fecha="x", emisor_tipo="02",
                emisor_numero="3101234567",
                xml_base64="PHhtbC8+",
            )
        body = mp.call_args.kwargs["json"]
        assert "receptor" not in body

    def test_send_400_raises_send_error_with_status(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            return_value=_send_resp(400),
        ):
            with pytest.raises(HaciendaSendError) as exc:
                c.send_document(
                    clave="x", fecha="x", emisor_tipo="02",
                    emisor_numero="3101234567",
                    xml_base64="PHhtbC8+",
                )
        assert exc.value.http_status == 400

    def test_send_401_retries_with_fresh_token(self):
        """
        Si Hacienda responde 401 (token expirado), el cliente debe:
        1) invalidar el token cacheado,
        2) pedir uno nuevo al IdP,
        3) reintentar el POST original.
        """
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c, "old-token")
        with patch("app.einvoice.hacienda_client.requests.post") as mp:
            mp.side_effect = [
                _send_resp(401),                    # primer intento → token expirado
                _token_resp("new-token"),           # IdP retorna token nuevo
                _send_resp(202, {}),                # reintento exitoso
            ]
            result = c.send_document(
                clave="x", fecha="x", emisor_tipo="02",
                emisor_numero="3101234567",
                xml_base64="PHhtbC8+",
            )
        assert result["status"] == "RECIBIDO"
        assert mp.call_count == 3

    def test_send_connection_error_raises_send_error(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            side_effect=requests.ConnectionError("dns"),
        ):
            with pytest.raises(HaciendaSendError, match="No se pudo conectar"):
                c.send_document(
                    clave="x", fecha="x", emisor_tipo="02",
                    emisor_numero="3101234567",
                    xml_base64="PHhtbC8+",
                )

    def test_send_timeout_raises_send_error(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        with patch(
            "app.einvoice.hacienda_client.requests.post",
            side_effect=requests.Timeout(),
        ):
            with pytest.raises(HaciendaSendError, match="Timeout"):
                c.send_document(
                    clave="x", fecha="x", emisor_tipo="02",
                    emisor_numero="3101234567",
                    xml_base64="PHhtbC8+",
                )


# ═══════════════════════════════════════════════════════════
# 4. HaciendaClient — consulta de estado (check_status)
# ═══════════════════════════════════════════════════════════

class TestHaciendaClientCheckStatus:

    def test_status_aceptado(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "clave": "x",
            "ind-estado": "aceptado",
            "fecha": "2026-05-23",
            "respuesta-xml": "PHhtbD4=",
        }
        with patch("app.einvoice.hacienda_client.requests.get", return_value=resp):
            result = c.check_status("x")
        assert result["ind_estado"] == "aceptado"
        assert result["respuesta_xml"] == "PHhtbD4="
        assert result["clave"] == "x"

    def test_status_404_returns_no_encontrado(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        resp = MagicMock()
        resp.status_code = 404
        with patch("app.einvoice.hacienda_client.requests.get", return_value=resp):
            result = c.check_status("x")
        assert result["ind_estado"] == "NO_ENCONTRADO"
        assert result["respuesta_xml"] == ""

    def test_status_500_raises(self):
        c = HaciendaClient(env="sandbox", user="u", password="p")
        _seed_token(c)
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "internal error"
        with patch("app.einvoice.hacienda_client.requests.get", return_value=resp):
            with pytest.raises(HaciendaSendError) as exc:
                c.check_status("x")
        assert exc.value.http_status == 500


# ═══════════════════════════════════════════════════════════
# 5. send_einvoice_to_hacienda — flujo completo con BD
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def db():
    """BD SQLite en memoria, aislada por test."""
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
def seeded(db):
    """Crea IssuerProfile + Customer + Sale + ElectronicInvoice listo para enviar."""
    from app.db.models.issuer_profile import IssuerProfile
    from app.db.models.customer import Customer
    from app.db.models.sale import Sale
    from app.db.models.cash_session import CashSession
    from app.db.models.electronic_invoice import ElectronicInvoice
    from app.utils.dt import today_cr, utcnow

    issuer = IssuerProfile(
        legal_name="Ferretería Test S.A.",
        commercial_name="Ferretería Test",
        id_type="02",
        id_number="3101234567",
        email="test@ferreteria.cr",
        phone="22001234",
    )
    db.add(issuer)

    customer = Customer(
        id=1, name="Cliente X",
        id_type="01", id_number="123456789",
        is_active=True,
    )
    db.add(customer)

    cs = CashSession(
        id=1, date=today_cr(),
        opening_amount=Decimal("0"), status="open",
    )
    db.add(cs)
    db.flush()

    sale = Sale(
        id=1,
        customer_id=1,
        total=Decimal("1130"),
        payment_method="Efectivo",
        cash_session_id=cs.id,
        status="ACTIVA",
        document_type="01",
        created_at=utcnow(),
    )
    db.add(sale)

    einv = ElectronicInvoice(
        id=1,
        sale_id=1,
        document_type="01",
        clave="50601012600310123456700100001010000000001123456789",
        consecutivo="00100001010000000001",
        status="XML_READY",
        xml_signed="<xml>contenido</xml>",
        tries=0,
    )
    db.add(einv)
    db.commit()

    return {
        "issuer": issuer,
        "customer": customer,
        "sale": sale,
        "einv": einv,
    }


class TestSendEinvoiceFlow:

    def test_success_marks_sent(self, db, seeded):
        """Camino feliz: XML_READY → SENT con sent_at, tries++, last_error limpio."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.return_value = {
            "status": "RECIBIDO", "http_status": 202,
        }

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            result = send_einvoice_to_hacienda(db, seeded["einv"].id)

        assert result["success"] is True
        assert result["status"] == "SENT"
        assert result["tries"] == 1

        db.refresh(seeded["einv"])
        assert seeded["einv"].status == "SENT"
        assert seeded["einv"].sent_at is not None
        assert seeded["einv"].tries == 1
        assert seeded["einv"].last_error is None
        assert seeded["einv"].hacienda_status == "RECIBIDO"

    def test_passes_receptor_from_customer(self, db, seeded):
        """El receptor debe extraerse del Customer asociado a la Sale."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.return_value = {"status": "RECIBIDO"}

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            send_einvoice_to_hacienda(db, seeded["einv"].id)

        call_kwargs = mock_client.send_document.call_args.kwargs
        assert call_kwargs["receptor_tipo"] == "01"
        assert call_kwargs["receptor_numero"] == "123456789"
        assert call_kwargs["emisor_tipo"] == "02"
        assert call_kwargs["emisor_numero"] == "3101234567"
        assert call_kwargs["clave"] == seeded["einv"].clave

    def test_fecha_uses_cr_offset(self, db, seeded):
        """Fix 2.1: la fecha enviada a Hacienda debe llevar offset -06:00."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.return_value = {"status": "RECIBIDO"}

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            send_einvoice_to_hacienda(db, seeded["einv"].id)

        fecha = mock_client.send_document.call_args.kwargs["fecha"]
        assert fecha.endswith("-06:00"), f"Fecha sin offset CR: {fecha}"

    def test_network_error_queues_offline(self, db, seeded):
        """Error de red → status QUEUED, flag offline=True."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.side_effect = HaciendaSendError(
            "No se pudo conectar al API de Hacienda: connection refused"
        )

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            result = send_einvoice_to_hacienda(db, seeded["einv"].id)

        assert result["success"] is False
        assert result["offline"] is True
        assert result["status"] == "QUEUED"

        db.refresh(seeded["einv"])
        # _enqueue_offline cambia el status del einv en BD
        assert seeded["einv"].status == "QUEUED"

    def test_timeout_error_queues_offline(self, db, seeded):
        """Timeout también se considera error de red."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.side_effect = HaciendaSendError(
            "Timeout enviando comprobante a Hacienda"
        )

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            result = send_einvoice_to_hacienda(db, seeded["einv"].id)

        assert result["offline"] is True
        assert result["status"] == "QUEUED"

    def test_non_network_error_marks_send_error(self, db, seeded):
        """Rechazo de Hacienda (HTTP 400) → SEND_ERROR, NO se encola."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.side_effect = HaciendaSendError(
            "Hacienda rechazó el comprobante (HTTP 400)",
            http_status=400,
            response_body="campo inválido",
        )

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            result = send_einvoice_to_hacienda(db, seeded["einv"].id)

        assert result["success"] is False
        assert "offline" not in result

        db.refresh(seeded["einv"])
        assert seeded["einv"].status == "SEND_ERROR"
        assert "HTTP 400" in seeded["einv"].last_error
        assert seeded["einv"].tries == 1

    def test_config_error_from_send_marks_send_error(self, db, seeded):
        """
        Si `send_document` lanza HaciendaConfigError (poco común — la config
        se valida normalmente en `get_hacienda_client`), el except sí la
        atrapa y marca SEND_ERROR. Nota: si la falla ocurre en
        `get_hacienda_client()`, NO está dentro del try y la excepción
        propaga al caller — eso es un comportamiento separado, no este test.
        """
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        mock_client = MagicMock()
        mock_client.send_document.side_effect = HaciendaConfigError(
            "config corrupta"
        )

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            result = send_einvoice_to_hacienda(db, seeded["einv"].id)

        assert result["success"] is False
        db.refresh(seeded["einv"])
        assert seeded["einv"].status == "SEND_ERROR"
        assert "config corrupta" in seeded["einv"].last_error

    def test_missing_xml_signed_rejected(self, db, seeded):
        """Sin XML firmado, no se intenta el envío."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        seeded["einv"].xml_signed = None
        db.commit()

        with pytest.raises(ValueError, match="XML firmado"):
            send_einvoice_to_hacienda(db, seeded["einv"].id)

    def test_missing_clave_rejected(self, db, seeded):
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        seeded["einv"].clave = None
        db.commit()

        with pytest.raises(ValueError, match="clave"):
            send_einvoice_to_hacienda(db, seeded["einv"].id)

    def test_wrong_status_rejected(self, db, seeded):
        """Solo XML_READY o SEND_ERROR son enviables. SENT NO."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        seeded["einv"].status = "SENT"
        db.commit()

        with pytest.raises(ValueError, match="XML_READY"):
            send_einvoice_to_hacienda(db, seeded["einv"].id)

    def test_nonexistent_einvoice_rejected(self, db, seeded):
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        with pytest.raises(ValueError, match="no existe"):
            send_einvoice_to_hacienda(db, 99999)

    def test_retry_from_send_error_clears_last_error(self, db, seeded):
        """Si un einv en SEND_ERROR se reintenta y ahora pasa, last_error → None."""
        from app.utils.hacienda_api import send_einvoice_to_hacienda

        seeded["einv"].status = "SEND_ERROR"
        seeded["einv"].last_error = "error previo HTTP 500"
        seeded["einv"].tries = 2
        db.commit()

        mock_client = MagicMock()
        mock_client.send_document.return_value = {"status": "RECIBIDO"}

        with patch(
            "app.utils.hacienda_api.get_hacienda_client",
            return_value=mock_client,
        ):
            result = send_einvoice_to_hacienda(db, seeded["einv"].id)

        assert result["success"] is True
        db.refresh(seeded["einv"])
        assert seeded["einv"].status == "SENT"
        assert seeded["einv"].last_error is None
        assert seeded["einv"].tries == 3