# ui/utils/http_worker.py
"""
FASE 1 — Fix 1.1 / 1.2: Infraestructura HTTP asíncrona para la capa UI.

Problema:
  Las vistas PySide6 hacían requests.get/post directamente en el hilo principal
  de Qt, congelando la interfaz hasta que el servidor respondiera. Además,
  117 llamadas no tenían timeout, arriesgando congelamientos indefinidos.

Solución:
  Este módulo provee dos mecanismos:

  1. HttpWorker (QRunnable) — Para control granular:
       worker = HttpWorker("get", url, headers=h)
       worker.signals.success.connect(self._on_data)
       worker.signals.error.connect(self._on_error)
       QThreadPool.globalInstance().start(worker)

  2. api_call() — Función de conveniencia (cubre el 90% de los casos):
       api_call("get", url, headers=h,
                on_success=self._on_data,
                on_error=self._on_error)

Todas las llamadas incluyen timeout por defecto (15s).
Los signals se entregan al hilo principal de Qt automáticamente,
así que los callbacks pueden actualizar la UI sin problemas.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)

# ─── Configuración ─────────────────────────────────────────────
DEFAULT_TIMEOUT = 15          # segundos — suficiente para localhost
CONNECT_TIMEOUT = 5           # tiempo máximo para establecer conexión
POOL_MAX_THREADS = 6          # hilos concurrentes en el pool

# Señal especial que indica que el token expiró (401)
AUTH_EXPIRED_SENTINEL = "__AUTH_EXPIRED__"

# ── FASE 7 — Fix 7.3: Sesión HTTP compartida para reutilizar conexiones ──
# requests.get/post crean una conexión TCP nueva en cada llamada.
# Un requests.Session reutiliza conexiones via HTTP keep-alive,
# evitando el overhead de TCP handshake en cada request a localhost.
# El pool_maxsize debe coincidir con POOL_MAX_THREADS para que cada
# hilo del QThreadPool pueda tener su propia conexión keep-alive.
_http_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=1,          # un solo host (127.0.0.1)
    pool_maxsize=POOL_MAX_THREADS,  # una conexión por hilo del pool
    max_retries=0,               # sin reintentos automáticos
)
_http_session.mount("http://", _adapter)


# ═══════════════════════════════════════════════════════════════
# Signals — deben vivir en un QObject, no en QRunnable
# ═══════════════════════════════════════════════════════════════
class WorkerSignals(QObject):
    """
    Signals emitidos por HttpWorker.
    Qt garantiza que los slots conectados se ejecuten en el hilo
    del receptor (el hilo principal de la UI) si la conexión es
    Qt.AutoConnection (default).
    """
    success = Signal(object)    # datos parseados (dict, list, str)
    error = Signal(str)         # mensaje de error legible
    finished = Signal()         # siempre emitido al final (éxito o error)
    auth_expired = Signal()     # emitido cuando el servidor responde 401


# ═══════════════════════════════════════════════════════════════
# HttpWorker — Ejecuta un request HTTP en el thread pool de Qt
# ═══════════════════════════════════════════════════════════════
class HttpWorker(QRunnable):
    """
    Ejecuta un request HTTP en un hilo del QThreadPool.

    Uso:
        worker = HttpWorker("get", "http://127.0.0.1:8000/products", headers={...})
        worker.signals.success.connect(self._on_products_loaded)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self._set_loading(False))
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(self, method: str, url: str, **kwargs):
        super().__init__()
        self.signals = WorkerSignals()
        self.method = method.lower()
        self.url = url
        self.kwargs = kwargs

        # ── FASE 1 — Fix 1.2: Timeout obligatorio ──
        # Si no se pasó timeout, usar (CONNECT_TIMEOUT, DEFAULT_TIMEOUT)
        # El primero es para establecer conexión, el segundo para leer respuesta.
        if "timeout" not in self.kwargs:
            self.kwargs["timeout"] = (CONNECT_TIMEOUT, DEFAULT_TIMEOUT)

        # Auto-eliminar del pool al terminar
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        """Ejecutado en un hilo del pool — NUNCA tocar widgets Qt aquí."""
        try:
            fn = getattr(_http_session, self.method, None)
            if fn is None:
                self.signals.error.emit(f"Método HTTP inválido: {self.method}")
                return

            resp = fn(self.url, **self.kwargs)

            # ── Auth expirado ──
            if resp.status_code == 401:
                self.signals.auth_expired.emit()
                self.signals.error.emit(AUTH_EXPIRED_SENTINEL)
                return

            # ── Error HTTP (4xx/5xx) ──
            if not resp.ok:
                detail = self._extract_error_detail(resp)
                self.signals.error.emit(detail)
                return

            # ── Éxito: parsear JSON o devolver texto ──
            try:
                data = resp.json()
            except (ValueError, requests.exceptions.JSONDecodeError):
                data = resp.text

            self.signals.success.emit(data)

        except requests.exceptions.ConnectTimeout:
            self.signals.error.emit(
                "No se pudo conectar al servidor (timeout de conexión). "
                "Verifique que el sistema esté iniciado."
            )
        except requests.exceptions.ReadTimeout:
            self.signals.error.emit(
                "El servidor tardó demasiado en responder. "
                "Intente de nuevo en unos segundos."
            )
        except requests.exceptions.ConnectionError:
            self.signals.error.emit(
                "No se pudo conectar al servidor. "
                "¿Está Violette POS iniciado correctamente?"
            )
        except requests.exceptions.HTTPError as e:
            detail = self._extract_error_detail(e.response) if e.response else str(e)
            self.signals.error.emit(detail)
        except Exception as e:
            logger.error(f"Error HTTP inesperado: {e}", exc_info=True)
            self.signals.error.emit(f"Error inesperado: {e}")
        finally:
            self.signals.finished.emit()

    @staticmethod
    def _extract_error_detail(resp) -> str:
        """Extrae el mensaje de error de una respuesta FastAPI."""
        try:
            err_data = resp.json()
            # FastAPI usa "detail" para errores
            detail = err_data.get("detail") or err_data.get("message") or ""
            if isinstance(detail, list):
                # Pydantic validation errors
                msgs = [d.get("msg", str(d)) for d in detail]
                return "; ".join(msgs)
            if detail:
                return str(detail)
        except Exception:
            pass
        return f"Error del servidor (código {resp.status_code})"


# ═══════════════════════════════════════════════════════════════
# api_call() — Función de conveniencia
# ═══════════════════════════════════════════════════════════════
def api_call(
    method: str,
    url: str,
    *,
    on_success: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    on_auth_expired: Optional[Callable[[], None]] = None,
    **kwargs,
) -> HttpWorker:
    """
    Lanza un request HTTP asíncrono y conecta callbacks.

    Todos los callbacks se ejecutan en el hilo principal de Qt,
    así que es seguro actualizar la UI desde ellos.

    Args:
        method: "get", "post", "put", "delete", "patch"
        url: URL completa del endpoint
        on_success: callback(data) — datos parseados (dict/list/str)
        on_error: callback(msg) — mensaje de error legible
        on_finished: callback() — siempre se ejecuta al final
        on_auth_expired: callback() — token expirado (401)
        **kwargs: argumentos adicionales para requests (headers, json, params, etc.)

    Returns:
        HttpWorker — por si se necesita inspeccionar o cancelar

    Ejemplo:
        api_call(
            "get",
            f"{BASE_URL}/products",
            headers=self._auth_headers(),
            params={"search": "tornillo"},
            on_success=self._on_products_loaded,
            on_error=self._show_error,
            on_finished=lambda: self.loading_spinner.hide(),
        )
    """
    worker = HttpWorker(method, url, **kwargs)

    if on_success:
        worker.signals.success.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)
    if on_finished:
        worker.signals.finished.connect(on_finished)
    if on_auth_expired:
        worker.signals.auth_expired.connect(on_auth_expired)

    QThreadPool.globalInstance().start(worker)
    return worker


# ═══════════════════════════════════════════════════════════════
# Inicialización del pool
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# FnWorker — Ejecuta CUALQUIER función en el thread pool
# ═══════════════════════════════════════════════════════════════
class FnWorker(QRunnable):
    """
    Ejecuta una función arbitraria en un hilo del QThreadPool.
    Ideal para funciones de servicio que ya hacen requests internamente.

    Uso:
        worker = FnWorker(fetch_dashboard_summary)
        worker.signals.success.connect(self._on_summary)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.signals = WorkerSignals()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        """Ejecutado en un hilo del pool."""
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.success.emit(result)
        except requests.exceptions.ConnectionError:
            self.signals.error.emit(
                "No se pudo conectar al servidor. "
                "¿Está Violette POS iniciado correctamente?"
            )
        except requests.exceptions.Timeout:
            self.signals.error.emit(
                "El servidor tardó demasiado en responder."
            )
        except Exception as e:
            logger.error(f"Error en FnWorker: {e}", exc_info=True)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


def run_async(
    fn: Callable,
    *args,
    on_success: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
    **kwargs,
) -> FnWorker:
    """
    Ejecuta una función en el thread pool de Qt con callbacks.

    Perfecto para funciones de servicio que ya hacen HTTP internamente
    (como fetch_dashboard_summary, fetch_sales_today_total, etc.).

    Args:
        fn: función a ejecutar en background
        *args: argumentos posicionales para fn
        on_success: callback(result) — resultado de fn()
        on_error: callback(msg) — mensaje de error
        on_finished: callback() — siempre se ejecuta al final
        **kwargs: argumentos con nombre para fn

    Ejemplo:
        run_async(
            fetch_dashboard_summary,
            on_success=self._on_summary_loaded,
            on_error=lambda msg: show_toast(msg, success=False, parent=self),
        )
    """
    worker = FnWorker(fn, *args, **kwargs)

    if on_success:
        worker.signals.success.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)
    if on_finished:
        worker.signals.finished.connect(on_finished)

    QThreadPool.globalInstance().start(worker)
    return worker


# ═══════════════════════════════════════════════════════════════
# Inicialización del pool
# ═══════════════════════════════════════════════════════════════
def configure_thread_pool():
    """
    Configura el QThreadPool global con límites razonables.
    Llamar una vez al inicio de la app (antes de usar api_call).
    """
    pool = QThreadPool.globalInstance()
    pool.setMaxThreadCount(POOL_MAX_THREADS)
    logger.debug(f"QThreadPool configurado: max {POOL_MAX_THREADS} hilos")


# ═══════════════════════════════════════════════════════════════
# api_request() — Wrapper síncrono con timeout obligatorio
#
# Para acciones rápidas iniciadas por botones (crear, editar,
# eliminar) donde el usuario espera el resultado inmediato.
# NO usar para carga de datos — usar api_call() en su lugar.
# ═══════════════════════════════════════════════════════════════
def api_request(
    method: str,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> requests.Response:
    """
    Wrapper síncrono de requests con timeout garantizado.

    Uso para acciones de botón:
        try:
            resp = api_request("delete", f"{API_URL}/{id}", headers=h)
            if resp.status_code == 200:
                self.load_data()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    IMPORTANTE: Solo para acciones rápidas que el usuario inicia
    explícitamente (click en botón). Para carga de datos usar api_call().
    """
    kwargs["timeout"] = (CONNECT_TIMEOUT, timeout)
    fn = getattr(_http_session, method.lower())
    return fn(url, **kwargs)