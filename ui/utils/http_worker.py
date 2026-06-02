# ui/utils/http_worker.py
"""
HTTP con I/O en hilo de fondo PURO + bombeo de eventos en el main thread.

═══════════════════════════════════════════════════════════════
HISTORIA Y RAZÓN DEL DISEÑO
═══════════════════════════════════════════════════════════════

Versiones muy anteriores usaban QThreadPool + QRunnable + WorkerSignals
para ejecutar HTTP requests en background. El patrón es estándar en
Qt, pero en este entorno específico:

  - PySide6 6.8.1
  - Python 3.12
  - Windows
  - requests 2.33.1 / urllib3 2.6.3

producía crashes binarios ("Windows fatal exception: access violation")
intermitentes y difíciles de diagnosticar, originados en distintos
patrones: race conditions en sockets, signals pendientes a QObjects
ya destruidos, event filters globales sobrevivientes a sus dueños,
WorkerSignals GC'd antes de que su emit se procesara, etc.

La causa raíz era SIEMPRE la misma categoría: OBJETOS Qt cruzando hilos
(QRunnable/QObject/Signal vivos en el worker y emitidos al main thread).

Como solución intermedia se pasó TODO a síncrono en el main thread, lo
que eliminó los crashes pero congelaba la ventana en operaciones lentas
(reportes, analítica, historial grande, exportes, envíos a Hacienda).

═══════════════════════════════════════════════════════════════
DISEÑO ACTUAL (FASE 2) — responsivo y SIN la categoría de crash vieja
═══════════════════════════════════════════════════════════════

Ahora el trabajo de RED corre en un threading.Thread de Python PURO que
NUNCA toca Qt (ni widgets, ni signals, ni QObjects). El resultado vuelve
por valor tras join(), y los callbacks se ejecutan SIEMPRE en el main
thread, igual que antes. Mientras el hilo trabaja, el main thread bombea
solo eventos que no son de input (ExcludeUserInputEvents) para que la
ventana siga viva sin aceptar clicks. Ver _run_blocking_io para el detalle
y las garantías de seguridad (incluida la guardia de re-entrancia).

Esto evita la categoría de crash vieja (no hay objetos Qt en el worker) y
a la vez elimina los congelamientos. En localhost casi todo es rápido y ni
siquiera se llega a bombear (período de gracia).

═══════════════════════════════════════════════════════════════
API PÚBLICA — IDÉNTICA A LAS VERSIONES ANTERIORES
═══════════════════════════════════════════════════════════════

Para que ningún otro archivo del proyecto necesite cambiar, este
módulo mantiene las mismas funciones con las mismas firmas:

  - api_call(method, url, ..., on_success, on_error, on_finished,
             on_auth_expired, owner, **kwargs)
  - run_async(fn, *args, on_success, on_error, on_finished, owner,
              **kwargs)
  - api_request(method, url, *, timeout, **kwargs)
  - configure_thread_pool()   ← no-op, queda por compatibilidad

Los callbacks se invocan ANTES de que `api_call` retorne (igual que en la
versión síncrona). Como casi todo el código del proyecto sólo espera
resultados vía callbacks, esto es transparente.

═══════════════════════════════════════════════════════════════
FASE 6 — Fix 6.X: Auto-refresh client-side ante 401
═══════════════════════════════════════════════════════════════

Antes: cualquier 401 emitía AUTH_EXPIRED_SENTINEL → el caller
abría el diálogo de re-login.

Ahora: cuando llega un 401 en un endpoint que NO es de auth, se
intenta /users/refresh con el refresh_token persistido y, si
funciona, se reintenta el request UNA vez con el nuevo
access_token. Solo si el refresh falla (o no hay refresh_token)
emitimos AUTH_EXPIRED_SENTINEL como antes.

Esto es transparente para todos los callers existentes: no cambian
firma ni semántica. La única diferencia visible es que un
access_token expirado deja de molestar al usuario cuando hay
refresh_token válido.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import requests
from PySide6.QtCore import QEventLoop, Qt, QObject
from PySide6.QtWidgets import QApplication

from ui.utils.exception_hooks import safe_slot

logger = logging.getLogger(__name__)

# ─── Configuración ─────────────────────────────────────────────
DEFAULT_TIMEOUT = 15
CONNECT_TIMEOUT = 5

# ── FASE 2 — Timeout para operaciones que el backend resuelve hablando
# con Hacienda (envío / consulta de comprobantes). El backend espera
# hasta 30s a Hacienda (hacienda_client._HTTP_TIMEOUT = 30). La UI DEBE
# esperar MÁS que eso; si la UI cortara antes (en 15s o incluso a los
# mismos 30s, empatando con el backend), el usuario vería "el servidor
# tardó demasiado" aunque el envío SÍ hubiera tenido éxito en el backend.
# 45s da margen para que el backend siempre termine primero y devuelva la
# respuesta real (aceptado / rechazado / error concreto).
SLOW_READ_TIMEOUT = 45

# Rutas cuyo backend puede tardar por hablar con Hacienda.
_SLOW_PATH_HINTS = ("/einvoices",)


def _read_timeout_for(url: str, explicit: Optional[int] = None) -> int:
    """Resuelve el read-timeout apropiado para una URL.

    - Si el caller pasó un timeout explícito, se respeta.
    - Endpoints de comprobantes electrónicos (/einvoices…) → SLOW_READ_TIMEOUT
      (mayor que el timeout del backend hacia Hacienda).
    - El resto → DEFAULT_TIMEOUT.
    """
    if explicit is not None:
        return explicit
    try:
        path = urlsplit(url).path
    except Exception:
        return DEFAULT_TIMEOUT
    if any(hint in path for hint in _SLOW_PATH_HINTS):
        return SLOW_READ_TIMEOUT
    return DEFAULT_TIMEOUT

# Señal especial que indica que el token expiró (401)
AUTH_EXPIRED_SENTINEL = "__AUTH_EXPIRED__"

# ── FASE 6 — Fix 6.X: Endpoints que NO disparan refresh+retry ──
# Reintentar un 401 sobre /users/login o /users/refresh entraría en
# loop: el refresh devuelve 401, intentamos refrescar de nuevo, etc.
_AUTH_PATHS_NO_RETRY = (
    "/users/login",
    "/users/refresh",
    "/users/setup",
)

# Una única Session global compartida. Las requests pueden ahora correr
# en un hilo de fondo (ver _run_blocking_io) además del main thread, pero
# es seguro: NUNCA mutamos el estado de la Session (headers/auth/cookies se
# pasan por request, no se guardan en la Session), y el pool de urllib3 es
# thread-safe. El pool se dimensiona para tolerar una operación lenta en
# vuelo + alguna request corta concurrente sin quedarse sin conexiones.
_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=4,
    pool_maxsize=4,
    max_retries=0,
)
_http_session.mount("http://", _adapter)
_http_session.mount("https://", _adapter)


# ═══════════════════════════════════════════════════════════════
# FASE 2.8 — Fix 2.8 (Camino A): Feedback visual sin tocar threading
# ═══════════════════════════════════════════════════════════════
#
# Estrategia conservadora: NO migramos a QThread+QObject (eso ya falló
# antes — ver el comment al inicio del archivo). En su lugar damos al
# usuario señal clara de que la app está trabajando:
#
#   1. Cursor de espera durante la request (Qt.WaitCursor).
#   2. processEvents(ExcludeUserInputEvents) para que el cambio de
#      cursor se renderice antes de iniciar la request bloqueante.
#      `ExcludeUserInputEvents` previene re-entrancia (clicks
#      durante el processEvents no se procesan, evitando que el
#      usuario dispare otra request mientras la actual está en vuelo).
#   3. Restauración garantizada del cursor en `finally` para que un
#      error en el callback no deje el cursor pegado.
#
# Para una operación de 1-3s en una ferretería en Costa Rica, esto
# convierte "la app se cuelga" en "la app muestra reloj de arena",
# que es expectativa estándar para POS de escritorio.
# ═══════════════════════════════════════════════════════════════
def _set_busy(busy: bool) -> None:
    """
    Muestra/restaura el cursor de espera del cursor de Qt.

    Defensivo:
      - Si no hay QApplication (modo headless / tests), no-op.
      - El stack interno de Qt maneja anidamiento (calls anidados
        de api_call → api_call funcionan correctamente).
    """
    app = QApplication.instance()
    if app is None:
        return
    if busy:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        # Forzar render inmediato del cambio de cursor SIN procesar
        # input del usuario (re-entrancia → otro click → otro api_call
        # → stack potencialmente sin fondo). Solo paint/timer events.
        app.processEvents(QEventLoop.ExcludeUserInputEvents)
    else:
        QApplication.restoreOverrideCursor()


# ═══════════════════════════════════════════════════════════════
# FASE 2 — Fix: UI responsiva durante operaciones lentas
# ═══════════════════════════════════════════════════════════════
#
# Problema: hacer el HTTP síncrono en el main thread congela la ventana
# durante operaciones lentas (reportes, analítica, historial grande,
# exportes, envíos a Hacienda). En localhost casi todo es rápido (~10-50ms),
# pero las pocas operaciones lentas dejaban la app en "No responde".
#
# Solución (sin reintroducir los crashes del viejo QThreadPool):
#   - El trabajo de RED corre en un hilo de fondo de Python puro
#     (threading.Thread). Ese hilo SOLO hace requests/parseo: NUNCA toca
#     widgets, signals ni QObjects. Por eso no hay objetos Qt cruzando
#     hilos — que era el origen de los access violations del diseño viejo
#     (QRunnable + WorkerSignals emitidos a QObjects ya destruidos, etc.).
#   - El resultado se devuelve por valor tras join(); los callbacks se
#     ejecutan DESPUÉS, en el main thread, igual que siempre.
#   - Mientras el hilo trabaja, el main thread bombea SOLO eventos que no
#     son de input (paint, timers, señales en cola) con
#     ExcludeUserInputEvents. Así la ventana sigue pintando y Windows no
#     marca "No responde", pero NO se aceptan clicks → el usuario no puede
#     disparar otra operación encima (evita re-entrancia descontrolada).
#
# Período de gracia: las llamadas rápidas (≤ _PUMP_GRACE_SECONDS) terminan
# sin que se procese un solo evento → su comportamiento es idéntico al
# síncrono de antes. El bombeo solo se activa si la operación se alarga.
#
# Re-entrancia: si un QTimer de debounce (búsquedas) dispara otra request
# durante el bombeo, se detecta con _pump_depth y se ejecuta DIRECTO (sin
# anidar event loops). Igual fuera del main thread (p. ej. un QThread de
# otra vista): ejecución directa, sin bombear.
# ═══════════════════════════════════════════════════════════════
_PUMP_GRACE_SECONDS = 0.05   # llamadas más rápidas que esto no bombean
_PUMP_SLICE_MS = 15          # ms máx. por ciclo de processEvents
_PUMP_POLL_SECONDS = 0.005   # respiro entre ciclos
_pump_depth = 0              # guardia de re-entrancia (solo main thread)


def _on_main_thread() -> bool:
    """True si corremos en el hilo principal (el dueño del event loop Qt)."""
    return threading.current_thread() is threading.main_thread()


def _run_blocking_io(work: Callable[[], Any]) -> Any:
    """Ejecuta `work()` —función de RED PURA, que NO toca Qt— sin congelar
    la UI.

    Devuelve lo que devuelva `work()`, o relanza su excepción en el main
    thread (para que el manejo de errores de los callers no cambie).
    """
    global _pump_depth
    app = QApplication.instance()

    # Sin QApplication (tests/headless), fuera del main thread (un QThread
    # de otra vista), o re-entrante (un timer disparó esto durante un
    # bombeo) → ejecución directa, sin anidar event loops.
    if app is None or not _on_main_thread() or _pump_depth > 0:
        return work()

    result: dict[str, Any] = {}
    done = threading.Event()

    def _runner() -> None:
        try:
            result["value"] = work()
        except BaseException as exc:        # se relanza en el main thread
            result["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_runner, name="vpx-http", daemon=True)
    worker.start()

    # Llamadas rápidas: salir sin tocar el event loop (comportamiento
    # idéntico al síncrono previo, sin riesgo de re-entrancia).
    if not done.wait(_PUMP_GRACE_SECONDS):
        _pump_depth += 1
        try:
            while not done.is_set():
                app.processEvents(QEventLoop.ExcludeUserInputEvents, _PUMP_SLICE_MS)
                done.wait(_PUMP_POLL_SECONDS)
            # Último ciclo para vaciar pintura pendiente antes de retornar.
            app.processEvents(QEventLoop.ExcludeUserInputEvents)
        finally:
            _pump_depth -= 1

    worker.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


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


def _is_auth_endpoint(url: str) -> bool:
    """True si la URL apunta a un endpoint propio de auth (no reintentar)."""
    try:
        path = urlsplit(url).path
    except Exception:
        return False
    return any(path.endswith(p) for p in _AUTH_PATHS_NO_RETRY)


def _replace_auth_header(headers, new_token: str):
    """Devuelve copia de `headers` con Authorization actualizado.

    Si headers es None o no contiene Authorization, retorna headers
    intacto. No agregamos Authorization si el caller no la pasó: eso
    cambiaría la semántica del request original.
    """
    if not headers:
        return headers
    new_headers = dict(headers)
    for k in list(new_headers.keys()):
        if isinstance(k, str) and k.lower() == "authorization":
            new_headers[k] = f"Bearer {new_token}"
    return new_headers


def _try_refresh_and_retry(method: str, url: str, **kwargs):
    """
    FASE 6 — Fix 6.X: Si recibimos 401 en un endpoint NO-auth y hay
    refresh_token, intentamos /users/refresh y reintentamos UNA vez.

    Retorna:
      - Response del retry si el refresh tuvo éxito.
      - None si no se intentó (sin refresh_token, endpoint de auth,
        o refresh falló). El caller debe tratar el 401 original.
    """
    if _is_auth_endpoint(url):
        return None

    # Import local para evitar ciclos al importar este módulo en startup.
    try:
        from ui.session_manager import session  # noqa: WPS433
    except Exception:
        return None

    if not session.refresh_token:
        return None

    expired_token = session.token
    if not session.try_refresh_access_token(expired_token=expired_token):
        # Sin red, refresh expirado, usuario desactivado, etc.
        return None

    # Renovado: reintentar con Authorization actualizado.
    new_kwargs = dict(kwargs)
    new_kwargs["headers"] = _replace_auth_header(kwargs.get("headers"), session.token)

    fn = getattr(_http_session, method.lower(), None)
    if fn is None:
        return None

    try:
        logger.debug("Auto-refresh: reintentando %s %s con token renovado", method, url)
        return fn(url, **new_kwargs)
    except Exception as e:
        # Si el retry mismo explota (red caída entre refresh y retry),
        # devolvemos None y el caller verá el AUTH_EXPIRED del 401 original.
        logger.warning(f"Retry tras refresh falló: {e}")
        return None


def _do_request(method: str, url: str, **kwargs):
    """
    Ejecuta el request HTTP y devuelve (success, payload_or_msg, status_code, auth_expired).

    success=True  → payload es el JSON parseado (o texto si no JSON).
    success=False → payload es el mensaje de error legible.

    No lanza excepciones: todas se capturan y se traducen.

    FASE 6 — Fix 6.X: Si vuelve 401 en endpoint NO-auth y hay refresh_token,
    se intenta refrescar el access_token y reintentar UNA vez antes de
    devolver AUTH_EXPIRED_SENTINEL.
    """
    # Timeout obligatorio (endpoint-aware: /einvoices usa SLOW_READ_TIMEOUT)
    if "timeout" not in kwargs:
        kwargs["timeout"] = (CONNECT_TIMEOUT, _read_timeout_for(url))

    try:
        fn = getattr(_http_session, method.lower(), None)
        if fn is None:
            return False, f"Método HTTP inválido: {method}", 0, False

        resp = fn(url, **kwargs)

        # ── Auth expirado: intentar refresh+retry antes de rendirse ──
        if resp.status_code == 401:
            # Liberar el socket del 401 antes de emitir el retry.
            try:
                resp.close()
            except Exception:
                pass

            retried = _try_refresh_and_retry(method, url, **kwargs)
            if retried is not None:
                resp = retried
                # Si el retry también dio 401, ahí sí: AUTH_EXPIRED real.
                if resp.status_code == 401:
                    return False, AUTH_EXPIRED_SENTINEL, 401, True
            else:
                # No se pudo refrescar (sin refresh_token, endpoint de auth,
                # refresh expirado…). 401 original es definitivo.
                return False, AUTH_EXPIRED_SENTINEL, 401, True

        # Error HTTP (incluye 401 si llegamos aquí por algún edge case raro)
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

    FASE 6 — Fix 6.X: on_auth_expired solo se dispara si el refresh
    automático también falló. Si el refresh tuvo éxito y el retry
    devolvió 200, esto es transparente: on_success se invoca como
    si nada hubiera pasado.
    """
    _label = f"{method.upper()} {url}"
    logger.debug("api_call ⇒ %s", _label)

    # FASE 2.8 — cursor de espera; FASE 2 — UI responsiva (event pump).
    _set_busy(True)
    try:
        success, payload, status, auth_expired = _run_blocking_io(
            lambda: _do_request(method, url, **kwargs)
        )

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
    finally:
        _set_busy(False)


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

    # FASE 2.8 — cursor de espera; FASE 2 — UI responsiva (event pump).
    _set_busy(True)
    try:
        try:
            result = _run_blocking_io(lambda: fn(*args, **kwargs))
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
    finally:
        _set_busy(False)


def api_request(
    method: str,
    url: str,
    *,
    timeout: Optional[int] = None,
    **kwargs,
) -> requests.Response:
    """
    Wrapper de requests con timeout garantizado.

    Devuelve el Response directamente — el caller maneja status_code
    y excepciones. Misma firma que antes salvo que `timeout` ahora es
    opcional: si no se pasa, se elige según el endpoint
    (endpoints /einvoices… usan SLOW_READ_TIMEOUT; el resto DEFAULT_TIMEOUT).
    Pasar un timeout explícito sigue funcionando igual.

    FASE 2 — UI responsiva: la request corre en un hilo de fondo y el main
    thread bombea eventos (sin aceptar input) si la operación se alarga,
    para que la ventana no quede en "No responde".

    FASE 6 — Fix 6.X: Si vuelve 401 en endpoint NO-auth y hay
    refresh_token, intenta /users/refresh y reintenta UNA vez. El
    Response retornado es el del retry si éste se ejecutó, o el del
    request original (probablemente 401) si el refresh falló o no
    se intentó. El caller no necesita cambios.
    """
    kwargs["timeout"] = (CONNECT_TIMEOUT, _read_timeout_for(url, timeout))

    def _do() -> requests.Response:
        fn = getattr(_http_session, method.lower())
        resp = fn(url, **kwargs)
        # FASE 6 — Fix 6.X: auto-refresh+retry transparente.
        if resp.status_code == 401:
            try:
                resp.close()
            except Exception:
                pass
            retried = _try_refresh_and_retry(method, url, **kwargs)
            if retried is not None:
                resp = retried
        return resp

    _set_busy(True)
    try:
        return _run_blocking_io(_do)
    finally:
        _set_busy(False)


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