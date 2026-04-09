"""
app/einvoice/hacienda_client.py — Cliente para el API de Comprobantes Electrónicos de Hacienda CR

Implementa según Anexo 3, v4.4:
  - Autenticación OAuth2 (OpenID Connect / Resource Owner Password Credential)
  - Envío de comprobantes electrónicos (POST /recepcion)
  - Consulta de estado (GET /recepcion/{clave})

USO:
    from app.einvoice.hacienda_client import HaciendaClient

    client = HaciendaClient(env="sandbox", user="cpf-...", password="xxx")
    client.send_document(clave, fecha, emisor, receptor, xml_base64)
    status = client.check_status(clave)

DEPENDENCIAS:
    pip install requests
"""
from __future__ import annotations

import base64
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# URLs según Anexo 3, v4.4
# ═══════════════════════════════════════════════════════════════

_URLS = {
    "sandbox": {
        "idp": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut-stag/protocol/openid-connect/token",
        "api": "https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1",
        "client_id": "api-stag",
    },
    "production": {
        "idp": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token",
        "api": "https://api.comprobanteselectronicos.go.cr/recepcion/v1",
        "client_id": "api-prod",
    },
}

# Margen de seguridad: refrescar token 60s antes de que expire
_TOKEN_REFRESH_MARGIN = 60

# Timeout para requests HTTP (segundos)
_HTTP_TIMEOUT = 30


# ═══════════════════════════════════════════════════════════════
# Excepciones específicas
# ═══════════════════════════════════════════════════════════════

class HaciendaAuthError(Exception):
    """Error de autenticación con el IdP de Hacienda."""
    pass


class HaciendaSendError(Exception):
    """Error enviando comprobante al API de Hacienda."""
    def __init__(self, message: str, http_status: int = 0, response_body: str = ""):
        super().__init__(message)
        self.http_status = http_status
        self.response_body = response_body


class HaciendaConfigError(Exception):
    """Configuración incompleta para conectarse a Hacienda."""
    pass


# ═══════════════════════════════════════════════════════════════
# Cliente principal
# ═══════════════════════════════════════════════════════════════

class HaciendaClient:
    """
    Cliente thread-safe para el API de Comprobantes Electrónicos de Hacienda CR.

    Maneja:
    - Obtención y refresh automático de tokens OAuth2
    - Envío de comprobantes (FE, TE, NC, ND, REP)
    - Consulta de estado por clave
    """

    def __init__(self, env: str = "sandbox", user: str = "", password: str = ""):
        if env not in _URLS:
            raise HaciendaConfigError(f"Ambiente inválido: {env}. Debe ser 'sandbox' o 'production'")
        if not user or not password:
            raise HaciendaConfigError(
                "HACIENDA_USER y HACIENDA_PASSWORD son requeridos. "
                "Configuralos en .env con las credenciales del ATV."
            )

        self._env = env
        self._user = user
        self._password = password
        self._urls = _URLS[env]

        # Token cache (thread-safe)
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0  # epoch

        logger.info(f"HaciendaClient inicializado | env={env} | api={self._urls['api']}")

    # ─── OAuth2 ──────────────────────────────────────────────

    def _request_token(self) -> dict:
        """
        Solicita un nuevo token al IdP de Hacienda.
        Grant Type: Resource Owner Password Credential.
        """
        data = {
            "grant_type": "password",
            "client_id": self._urls["client_id"],
            "username": self._user,
            "password": self._password,
        }

        logger.debug(f"Solicitando token OAuth2 a {self._urls['idp']}")

        try:
            resp = requests.post(
                self._urls["idp"],
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_HTTP_TIMEOUT,
            )
        except requests.ConnectionError as e:
            raise HaciendaAuthError(f"No se pudo conectar al IdP de Hacienda: {e}")
        except requests.Timeout:
            raise HaciendaAuthError("Timeout conectando al IdP de Hacienda")

        if resp.status_code != 200:
            body = resp.text[:500]
            logger.error(f"Error autenticación Hacienda HTTP {resp.status_code}: {body}")

            if resp.status_code == 401:
                raise HaciendaAuthError(
                    "Credenciales inválidas. Verificá HACIENDA_USER y HACIENDA_PASSWORD en .env. "
                    "El usuario tiene formato: cpf-01-1234-5678@comprobanteselectronicos.go.cr"
                )
            elif resp.status_code == 400:
                raise HaciendaAuthError(f"Solicitud de token rechazada por Hacienda: {body}")
            else:
                raise HaciendaAuthError(f"Error HTTP {resp.status_code} del IdP: {body}")

        token_data = resp.json()
        return token_data

    def _get_token(self) -> str:
        """
        Obtiene un token válido. Si el actual está por expirar o no existe, solicita uno nuevo.
        Thread-safe.
        """
        with self._lock:
            now = time.time()

            # Si el token aún es válido (con margen), reutilizar
            if self._access_token and now < (self._token_expires_at - _TOKEN_REFRESH_MARGIN):
                return self._access_token

            # Solicitar nuevo token
            token_data = self._request_token()

            self._access_token = token_data.get("access_token")
            if not self._access_token:
                raise HaciendaAuthError("El IdP no retornó access_token")

            expires_in = token_data.get("expires_in", 300)  # default 5 min
            self._token_expires_at = now + expires_in

            logger.info(f"Token OAuth2 obtenido | expira en {expires_in}s")
            return self._access_token

    def _auth_header(self) -> dict:
        """Retorna el header Authorization con el token vigente."""
        token = self._get_token()
        return {"Authorization": f"bearer {token}"}

    def invalidate_token(self):
        """Fuerza la renovación del token en la próxima llamada."""
        with self._lock:
            self._access_token = None
            self._token_expires_at = 0

    # ─── Envío de comprobantes ───────────────────────────────

    def send_document(
        self,
        *,
        clave: str,
        fecha: str,
        emisor_tipo: str,
        emisor_numero: str,
        receptor_tipo: Optional[str] = None,
        receptor_numero: Optional[str] = None,
        xml_base64: str,
        callback_url: Optional[str] = None,
    ) -> dict:
        """
        Envía un comprobante electrónico al API de Hacienda.

        Args:
            clave: Clave numérica de 50 dígitos
            fecha: Fecha de emisión RFC3339 (ej: "2025-03-26T14:30:00-06:00")
            emisor_tipo: Tipo de identificación del emisor ("01","02","03","04")
            emisor_numero: Número de cédula del emisor
            receptor_tipo: Tipo de ID del receptor (opcional para TE)
            receptor_numero: Número de cédula del receptor (opcional para TE)
            xml_base64: XML firmado codificado en Base64
            callback_url: URL para recibir respuesta asíncrona (opcional)

        Returns:
            dict con la respuesta de Hacienda

        Raises:
            HaciendaAuthError: Si falla la autenticación
            HaciendaSendError: Si falla el envío
        """
        url = f"{self._urls['api']}/recepcion"

        # Construir body según Anexo 3
        body: dict[str, Any] = {
            "clave": clave,
            "fecha": fecha,
            "emisor": {
                "tipoIdentificacion": emisor_tipo,
                "numeroIdentificacion": emisor_numero,
            },
            "comprobanteXml": xml_base64,
        }

        # Receptor: obligatorio para FE, opcional para TE
        if receptor_tipo and receptor_numero:
            body["receptor"] = {
                "tipoIdentificacion": receptor_tipo,
                "numeroIdentificacion": receptor_numero,
            }

        # Callback URL: Hacienda hace POST aquí con la respuesta
        if callback_url:
            body["callbackUrl"] = callback_url

        logger.info(f"Enviando comprobante a Hacienda | clave={clave} | url={url}")

        headers = {
            **self._auth_header(),
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(url, json=body, headers=headers, timeout=_HTTP_TIMEOUT)
        except requests.ConnectionError as e:
            raise HaciendaSendError(f"No se pudo conectar al API de Hacienda: {e}")
        except requests.Timeout:
            raise HaciendaSendError("Timeout enviando comprobante a Hacienda")

        # Hacienda responde:
        #   202 Accepted → comprobante recibido, procesando
        #   400 → error en el body/datos
        #   401 → token expirado (reintentar con nuevo token)
        #   500 → error interno de Hacienda

        if resp.status_code == 202:
            logger.info(f"Comprobante recibido por Hacienda | clave={clave}")
            result = {"status": "RECIBIDO", "http_status": 202}
            try:
                result["body"] = resp.json()
            except Exception:
                result["body"] = resp.text
            return result

        if resp.status_code == 401:
            # Token expirado — invalidar y reintentar una vez
            logger.warning("Token expirado, renovando...")
            self.invalidate_token()
            headers = {**self._auth_header(), "Content-Type": "application/json"}
            try:
                resp = requests.post(url, json=body, headers=headers, timeout=_HTTP_TIMEOUT)
            except Exception as e:
                raise HaciendaSendError(f"Error en reintento: {e}")

            if resp.status_code == 202:
                logger.info(f"Comprobante recibido (reintento) | clave={clave}")
                result = {"status": "RECIBIDO", "http_status": 202}
                try:
                    result["body"] = resp.json()
                except Exception:
                    result["body"] = resp.text
                return result

        # Cualquier otro código es error
        body_text = resp.text[:1000]
        logger.error(f"Error enviando a Hacienda HTTP {resp.status_code}: {body_text}")
        raise HaciendaSendError(
            f"Hacienda rechazó el comprobante (HTTP {resp.status_code})",
            http_status=resp.status_code,
            response_body=body_text,
        )

    # ─── Consulta de estado ──────────────────────────────────

    def check_status(self, clave: str) -> dict:
        """
        Consulta el estado de un comprobante por su clave.

        GET /recepcion/{clave}

        Returns:
            dict con:
                - ind_estado: "RECIBIDO" | "PROCESANDO" | "ACEPTADO" | "RECHAZADO"
                - fecha: fecha de la respuesta
                - respuesta_xml: XML de MensajeHacienda en base64 (si disponible)
        """
        url = f"{self._urls['api']}/recepcion/{clave}"

        logger.debug(f"Consultando estado en Hacienda | clave={clave}")

        headers = self._auth_header()

        try:
            resp = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        except requests.ConnectionError as e:
            raise HaciendaSendError(f"No se pudo conectar al API de Hacienda: {e}")
        except requests.Timeout:
            raise HaciendaSendError("Timeout consultando estado en Hacienda")

        if resp.status_code == 401:
            self.invalidate_token()
            headers = self._auth_header()
            try:
                resp = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
            except Exception as e:
                raise HaciendaSendError(f"Error en reintento: {e}")

        if resp.status_code == 200:
            data = resp.json()
            result = {
                "clave": data.get("clave", clave),
                "ind_estado": data.get("ind-estado", data.get("indEstado", "DESCONOCIDO")),
                "fecha": data.get("fecha", ""),
                "respuesta_xml": data.get("respuesta-xml", data.get("respuestaXml", "")),
            }
            logger.info(f"Estado Hacienda | clave={clave} | estado={result['ind_estado']}")
            return result

        if resp.status_code == 404:
            return {
                "clave": clave,
                "ind_estado": "NO_ENCONTRADO",
                "fecha": "",
                "respuesta_xml": "",
            }

        raise HaciendaSendError(
            f"Error consultando estado (HTTP {resp.status_code})",
            http_status=resp.status_code,
            response_body=resp.text[:500],
        )


# ═══════════════════════════════════════════════════════════════
# Singleton / Factory
# ═══════════════════════════════════════════════════════════════

_client_instance: Optional[HaciendaClient] = None
_client_lock = threading.Lock()


def get_hacienda_client() -> HaciendaClient:
    """
    Retorna un singleton del HaciendaClient configurado desde .env.
    Thread-safe. Lanza HaciendaConfigError si faltan credenciales.
    """
    global _client_instance

    with _client_lock:
        if _client_instance is not None:
            return _client_instance

        from app.core.credentials import hacienda_env, hacienda_user, hacienda_password

        env = hacienda_env()
        user = hacienda_user()
        password = hacienda_password()

        if not user or not password:
            raise HaciendaConfigError(
                "Las credenciales de Hacienda no están configuradas. "
                "Configuralas desde Ajustes > Facturación > Conexión con Hacienda, "
                "o en el archivo .env (HACIENDA_USER / HACIENDA_PASSWORD)."
            )

        _client_instance = HaciendaClient(env=env, user=user, password=password)
        return _client_instance


def reset_hacienda_client():
    """Fuerza recrear el cliente (útil si cambian las credenciales)."""
    global _client_instance
    with _client_lock:
        _client_instance = None


def get_connection_status() -> dict:
    """
    Retorna el estado de la conexión a Hacienda sin enviar nada.
    Útil para diagnóstico en la UI.
    """
    from app.core.credentials import (
        hacienda_env, hacienda_user, hacienda_password,
    )

    _h_env = hacienda_env()
    _h_user = hacienda_user()
    _h_pass = hacienda_password()

    result = {
        "configured": False,
        "env": _h_env,
        "user": _h_user or "",
        "api_url": "",
        "idp_url": "",
        "token_valid": False,
        "error": None,
    }

    if not _h_user or not _h_pass:
        result["error"] = "Credenciales de Hacienda no configuradas"
        return result

    urls = _URLS.get(_h_env, _URLS["sandbox"])
    result["api_url"] = urls["api"]
    result["idp_url"] = urls["idp"]
    result["configured"] = True

    # Intentar obtener token para verificar credenciales
    try:
        client = get_hacienda_client()
        client._get_token()
        result["token_valid"] = True
    except HaciendaAuthError as e:
        result["error"] = str(e)
    except HaciendaConfigError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"Error inesperado: {e}"

    return result