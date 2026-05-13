# ui/utils/http_worker.py
"""
HTTP síncrono en el main thread — SIN threading.

═══════════════════════════════════════════════════════════════
HISTORIA Y RAZÓN DEL CAMBIO
═══════════════════════════════════════════════════════════════

Versiones anteriores usaban QThreadPool + QRunnable + WorkerSignals
para ejecutar HTTP requests en background. El patrón es estándar en
Qt, pero en este entorno específico:

  - PySide6 6.8.1
  - Python 3.12
  - Windows
  - requests 2.33.1 / urllib3 2.6.3

produjo crashes binarios ("Windows fatal exception: access violation")
intermitentes y difíciles de diagnosticar, originados en distintos
patrones: race conditions en sockets, signals pendientes a QObjects
ya destruidos, event filters globales sobrevivientes a sus dueños,
WorkerSignals GC'd antes de que su emit se procesara, etc. Se
parchearon varios pero la lista parecía infinita.

Como el backend corre en localhost (127.0.0.1:8000) y cada request
tarda ~10-50ms, el costo de hacerlo síncrono en el main thread es
imperceptible para el usuario y elimina TODA la categoría de bugs
relacionada con threading.

═══════════════════════════════════════════════════════════════
API PÚBLICA — IDÉNTICA A LA VERSIÓN ASYNC
═══════════════════════════════════════════════════════════════

Para que ningún otro archivo del proyecto necesite cambiar, este
módulo mantiene las mismas funciones con las mismas firmas:

  - api_call(method, url, ..., on_success, on_error, on_finished,
             on_auth_expired, owner, **kwargs)
  - run_async(fn, *args, on_success, on_error, on_finished, owner,
              **kwargs)
  - api_request(method, url, *, timeout, **kwargs)
  - configure_thread_pool()   ← no-op, queda por compatibilidad

La única diferencia visible es que los callbacks se invocan ANTES
de que `api_call` retorne, no después. Como casi todo el código
del proyecto sólo espera resultados vía callbacks, esto es
transparente.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import requests
from PySide6.QtCore import QObject

from ui.utils.exception_hooks import safe_slot

logger = logging.getLogger(__name__)

# ─── Configuración ─────────────────────────────────────────────
DEFAULT_TIMEOUT = 15
CONNECT_TIMEOUT = 5

# Señal especial que indica que el token expiró (401)
AUTH_EXPIRED_SENTINEL = "__AUTH_EXPIRED__"

# Una única Session global. Como TODAS las requests corren en el
# main thread (síncronas), no hay race condition de threads.
# Mantenemos keep-alive porque seguimos hablando con el mismo host.
_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=2,
    pool_maxsize=2,
    max_retries=0,
)
_http_session.mount("http://", _adapter)
_http_session.mount("https://", _adapter)


# ═══════════════════════════════════════════════════════════════
# Helpers internos
# ═══════════════════════════════════════════════════════════════
def _extract_error_detail(resp) -> str:
    """Extrae el mensaje de error de una respuesta FastAPI."""
    try:
        err_data = resp.json()
        detail = err_data.get("detail") or err_data.get("message") or ""
        if isinstance(detail, list):
            msgs = [d.get("msg", str(d)) for d in detail]
            return "; ".join(msgs)
        if detail:
            return str(detail)
    except Exception:
        pass
    return f"Error del servidor (código {resp.status_code})"


def _do_request(method: str, url: str, **kwargs):
    """
    Ejecuta el request HTTP y devuelve (success, payload_or_msg, status_code, auth_expired).

    success=True  → payload es el JSON parseado (o texto si no JSON).
    success=False → payload es el mensaje de error legible.

    No lanza excepciones: todas se capturan y se traducen.
    """
    # Timeout obligatorio
    if "timeout" not in kwargs:
        kwargs["timeout"] = (CONNECT_TIMEOUT, DEFAULT_TIMEOUT)

    try:
        fn = getattr(_http_session, method.lower(), None)
        if fn is None:
            return False, f"Método HTTP inválido: {method}", 0, False

        resp = fn(url, **kwargs)

        # Auth expirado
        if resp.status_code == 401:
            return False, AUTH_EXPIRED_SENTINEL, 401, True

        # Error HTTP
        if not resp.ok:
            return False, _extract_error_detail(resp), resp.status_code, False

        # Éxito: parsear JSON o devolver texto
        try:
            data = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            data = resp.text

        return True, data, resp.status_code, False

    except requests.exceptions.ConnectTimeout:
        return False, ("No se pudo conectar al servidor (timeout de conexión). "
                       "Verifique que el sistema esté iniciado."), 0, False
    except requests.exceptions.ReadTimeout:
        return False, ("El servidor tardó demasiado en responder. "
                       "Intente de nuevo en unos segundos."), 0, False
    except requests.exceptions.ConnectionError:
        return False, ("No se pudo conectar al servidor. "
                       "¿Está Violette POS iniciado correctamente?"), 0, False
    except requests.exceptions.HTTPError as e:
        detail = _extract_error_detail(e.response) if e.response else str(e)
        return False, detail, 0, False
    except Exception as e:
        logger.error(f"Error HTTP inesperado: {e}", exc_info=True)
        return False, f"Error inesperado: {e}", 0, False


def _invoke_callback(cb: Optional[Callable], *args, label: str = "") -> None:
    """
    Invoca un callback con manejo defensivo. Cualquier excepción se
    loguea pero no se propaga.
    """
    if cb is None:
        return
    # Envolver con safe_slot para uniformidad con el patrón anterior
    # (logs ▶ / ◀ y captura de excepciones).
    wrapped = safe_slot(cb, label=label)
    wrapped(*args)


# ═══════════════════════════════════════════════════════════════
# API pública — equivalente a la versión async pero síncrona
# ═══════════════════════════════════════════════════════════════
def api_call(
    method: str,
    url: str,
    *,
    on_success: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    on_auth_expired: Optional[Callable[[], None]] = None,
    owner: Optional[QObject] = None,
    **kwargs,
) -> None:
    """
    Ejecuta un request HTTP SÍNCRONO en el main thread y dispara
    los callbacks correspondientes antes de retornar.

    Misma firma que la versión async para retrocompatibilidad. El
    parámetro `owner` ya no se usa (no hay threading), pero se
    acepta para no romper llamadores existentes.

    Orden de invocación:
      1. Si éxito → on_success(data)
      2. Si error → on_error(msg)
      3. Si 401   → on_auth_expired() + on_error(AUTH_EXPIRED_SENTINEL)
      4. Siempre  → on_finished()
    """
    _label = f"{method.upper()} {url}"
    logger.debug("api_call ⇒ %s", _label)

    success, payload, status, auth_expired = _do_request(method, url, **kwargs)

    try:
        if auth_expired:
            _invoke_callback(on_auth_expired, label=f"{_label} auth_expired")
            _invoke_callback(on_error, AUTH_EXPIRED_SENTINEL, label=f"{_label} error")
        elif success:
            logger.debug("api_call ◄ %s → %s", _label, status)
            _invoke_callback(on_success, payload, label=f"{_label} success")
        else:
            logger.debug("api_call ✖ %s → %s", _label, status)
            _invoke_callback(on_error, payload, label=f"{_label} error")
    finally:
        _invoke_callback(on_finished, label=f"{_label} finished")


def run_async(
    fn: Callable,
    *args,
    on_success: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    owner: Optional[QObject] = None,
    **kwargs,
) -> None:
    """
    Ejecuta una función SÍNCRONAMENTE en el main thread y dispara
    los callbacks. Misma firma que la versión async para
    retrocompatibilidad.
    """
    _label = getattr(fn, "__name__", "fn")
    logger.debug("run_async ⇒ %s", _label)

    try:
        result = fn(*args, **kwargs)
    except requests.exceptions.ConnectionError:
        _invoke_callback(
            on_error,
            "No se pudo conectar al servidor. ¿Está Violette POS iniciado correctamente?",
            label=f"{_label} error",
        )
        _invoke_callback(on_finished, label=f"{_label} finished")
        return
    except requests.exceptions.Timeout:
        _invoke_callback(
            on_error,
            "El servidor tardó demasiado en responder.",
            label=f"{_label} error",
        )
        _invoke_callback(on_finished, label=f"{_label} finished")
        return
    except Exception as e:
        logger.error(f"Error en run_async({_label}): {e}", exc_info=True)
        _invoke_callback(on_error, str(e), label=f"{_label} error")
        _invoke_callback(on_finished, label=f"{_label} finished")
        return

    _invoke_callback(on_success, result, label=f"{_label} success")
    _invoke_callback(on_finished, label=f"{_label} finished")


def api_request(
    method: str,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> requests.Response:
    """
    Wrapper síncrono de requests con timeout garantizado.

    Devuelve el Response directamente — el caller maneja status_code
    y excepciones. Mantiene la misma firma que la versión anterior.
    """
    kwargs["timeout"] = (CONNECT_TIMEOUT, timeout)
    fn = getattr(_http_session, method.lower())
    return fn(url, **kwargs)


# ═══════════════════════════════════════════════════════════════
# Compatibilidad: configure_thread_pool ya no hace nada útil
# pero se mantiene para que los llamadores existentes no rompan.
# ═══════════════════════════════════════════════════════════════
def configure_thread_pool():
    """
    No-op. Antes configuraba el QThreadPool global, ahora todas las
    requests son síncronas en el main thread. Se mantiene la función
    por retrocompatibilidad con login_view.py y launcher.py.
    """
    logger.debug("configure_thread_pool: HTTP es síncrono, nada que configurar.")