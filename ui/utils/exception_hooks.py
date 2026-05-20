# ui/utils/exception_hooks.py
"""
Manejo global de excepciones para PySide6.

PROBLEMA QUE RESUELVE
=====================
Desde PySide6 6.6 en adelante, las excepciones Python no capturadas
dentro de un slot (cualquier callback conectado a un signal — botones,
timers, `on_success`/`on_error` del HttpWorker, etc.) cierran el
proceso silenciosamente. La ventana desaparece sin mensaje de error.

Esto significa que CUALQUIER bug menor (un `KeyError` en un dict, un
`TypeError` por datos inesperados del backend, un `RuntimeError:
Internal C++ object already deleted` al tocar un widget destruido)
termina la aplicación entera en lugar de mostrar un mensaje y seguir
funcionando.

SOLUCIÓN
========
Instalar tres hooks globales ANTES de iniciar el loop de eventos:

  - sys.excepthook         → captura excepciones del main thread
                             (slots de Qt, timers, callbacks de signals).
  - threading.excepthook   → captura excepciones de hilos de background
                             (HttpWorker / FnWorker, por si alguna vez
                             escapa de su try/except interno).
  - faulthandler           → si Qt mismo segfaultea (raro pero posible),
                             al menos volcamos el stack al log.

Todos loguean el error completo, lo escriben a stderr, y muestran un
QMessageBox al usuario si hay una QApplication corriendo. La app sigue
viva en lugar de morir en silencio.

USO
===
Llamar UNA sola vez al inicio, idealmente JUSTO DESPUÉS de crear
QApplication (para que QMessageBox pueda mostrarse si ocurre un error
temprano):

    from PySide6.QtWidgets import QApplication
    from ui.utils.exception_hooks import install_global_exception_hooks

    app = QApplication(sys.argv)
    install_global_exception_hooks()
    ...
    sys.exit(app.exec())
"""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import traceback
from typing import Callable

logger = logging.getLogger(__name__)

# ── Estado interno ──────────────────────────────────────────────
_original_excepthook = sys.excepthook
_original_threading_excepthook = getattr(threading, "excepthook", None)
_installed = False

# Para evitar mostrar 200 QMessageBox seguidos si algo entra en bucle
_MAX_DIALOGS_PER_MINUTE = 5
_recent_dialogs: list[float] = []


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════
def _format_exception(exc_type, exc_value, exc_tb) -> str:
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def _can_show_dialog() -> bool:
    """
    Rate-limit de diálogos para evitar avalanchas de errores
    (por ejemplo si un timer falla cada 100ms).
    """
    import time

    now = time.monotonic()
    # Limpiar entradas viejas (más de 60 segundos)
    _recent_dialogs[:] = [t for t in _recent_dialogs if now - t < 60]
    if len(_recent_dialogs) >= _MAX_DIALOGS_PER_MINUTE:
        return False
    _recent_dialogs.append(now)
    return True


def _show_error_dialog(short_msg: str, full_trace: str) -> None:
    """
    Muestra un QMessageBox no-bloqueante al usuario.
    Si no hay QApplication o el rate-limit se excedió, no hace nada
    (solo loguea, que ya se hizo antes).
    Esta función SOLO debe llamarse desde el main thread.
    """
    if not _can_show_dialog():
        return

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            return  # aún no hay app de Qt; nada que mostrar

        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Ocurrió un error inesperado")
        box.setText(
            "Se produjo un error pero la aplicación seguirá funcionando.\n\n"
            "Si el problema se repite, revise el archivo data/logs/app.log "
            "para más detalles."
        )
        box.setInformativeText(short_msg)
        box.setDetailedText(full_trace)
        box.setStandardButtons(QMessageBox.Ok)
        # exec() bloquea hasta que el usuario cierre el diálogo, pero como
        # estamos en el main thread eso es el comportamiento esperado.
        box.exec()
    except Exception as e:
        # Si incluso el QMessageBox falla, no propagar: eso causaría
        # un loop infinito de excepciones dentro del excepthook.
        logger.error(f"No se pudo mostrar diálogo de error: {e}")


# ════════════════════════════════════════════════════════════════
# Hooks
# ════════════════════════════════════════════════════════════════
def _global_excepthook(exc_type, exc_value, exc_tb) -> None:
    """
    Reemplazo de sys.excepthook.

    Se invoca cuando una excepción no fue capturada en ningún
    try/except. En PySide6, esto incluye slots de Qt.
    """
    # KeyboardInterrupt → comportamiento normal de Python (no diálogo).
    if issubclass(exc_type, KeyboardInterrupt):
        if _original_excepthook is not None:
            _original_excepthook(exc_type, exc_value, exc_tb)
        return

    trace = _format_exception(exc_type, exc_value, exc_tb)

    # Log estructurado
    logger.error(
        "Excepción no manejada en hilo principal:\n%s",
        trace,
    )

    # Stderr (útil cuando se corre desde terminal)
    try:
        sys.stderr.write(trace)
        sys.stderr.flush()
    except Exception:
        pass

    # Diálogo al usuario (si Qt está vivo)
    short = f"{exc_type.__name__}: {exc_value}"
    _show_error_dialog(short, trace)


def _global_threading_excepthook(args) -> None:
    """
    Reemplazo de threading.excepthook (Python 3.8+).

    Se invoca cuando un thread termina por excepción no capturada.
    NUNCA tocar widgets Qt aquí — estamos en un hilo de background.
    """
    if args.exc_type is SystemExit:
        return

    trace = _format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    thread_name = getattr(args.thread, "name", "<unknown>") if args.thread else "<unknown>"

    logger.error(
        "Excepción no manejada en thread '%s':\n%s",
        thread_name,
        trace,
    )
    try:
        sys.stderr.write(trace)
        sys.stderr.flush()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# API pública
# ════════════════════════════════════════════════════════════════
def install_global_exception_hooks() -> None:
    """
    Instala los manejadores globales. Idempotente: llamadas adicionales
    no hacen nada.

    Llamar UNA sola vez al inicio de la app, después de crear
    QApplication.
    """
    global _installed
    if _installed:
        return

    sys.excepthook = _global_excepthook

    if hasattr(threading, "excepthook"):
        threading.excepthook = _global_threading_excepthook

    # ── Forzar line buffering en stdout/stderr ──
    # Sin esto, los prints/logs pueden quedar en buffer y perderse si
    # la app crashea repentinamente.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    # ── Visibilidad: logging detallado a stdout ──
    # El logger de la app escribe a data/logs/app.log, pero queremos
    # ver TODO en consola en tiempo real para diagnosticar el crash
    # actual. Si ya hay handlers configurados, no duplicamos.
    try:
        import logging as _logging
        root = _logging.getLogger()
        # ¿Ya hay un StreamHandler a stdout/stderr? Si no, agregar uno.
        has_console = any(
            isinstance(h, _logging.StreamHandler) and
            getattr(h, "stream", None) in (sys.stdout, sys.stderr)
            for h in root.handlers
        )
        if not has_console:
            # ── FASE 3.4 — Fix 3.4: NO contaminar root logger ──
            # Antes: console.setLevel(DEBUG) + root.setLevel(DEBUG).
            # Eso forzaba al root a DEBUG, inundando los archivos de log
            # con tráfico de SQLAlchemy, urllib3, etc., antes de que
            # `app/core/logger.py` tuviera oportunidad de silenciarlos.
            #
            # Ahora: handler a WARNING (suficiente para ver crashes en
            # consola si la app se levanta sin GUI) y NO tocamos
            # root.setLevel. El nivel del root lo decide `logger.py`.
            console = _logging.StreamHandler(sys.stderr)
            console.setLevel(_logging.WARNING)
            console.setFormatter(_logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            ))
            root.addHandler(console)
        # Silenciar loggers ruidosos como defensa por si exception_hooks
        # se instala ANTES que logger.py (orden de imports). Si logger.py
        # corre después, los re-aplica con el mismo nivel.
        for noisy in ("urllib3", "httpcore", "httpx", "asyncio", "PIL",
                      "sqlalchemy.engine", "uvicorn.access", "uvicorn.error"):
            _logging.getLogger(noisy).setLevel(_logging.WARNING)
    except Exception as e:
        sys.stderr.write(f"No se pudo configurar logging a consola: {e}\n")

    # ── faulthandler: dump a stderr Y a archivo persistente ──
    # Si la app crashea con SIGSEGV/access violation, el dump queda
    # guardado en data/logs/crash.log incluso si la consola se cierra.
    try:
        import faulthandler as _fh
        if not _fh.is_enabled():
            _fh.enable()  # default: stderr
        # Adicional: dump a archivo. faulthandler.register sería para señales
        # específicas; usamos enable con un archivo extra abierto en append.
        try:
            # ── FASE 3.3 — Fix 3.3: path absoluto, no relativo al CWD ──
            # Antes: `Path("data") / "logs"` (relativo). Funcionaba si
            # `launcher.py` hacía `os.chdir`, pero si alguien lanzaba el
            # módulo directo (ej. `python -m app.main` desde otro dir,
            # o pytest desde subdir), el crash.log terminaba en lugares
            # impredecibles.
            #
            # Ahora: usar DATA_DIR absoluto desde la config (apunta a
            # APP_DIR/data, calculado al cargar config.py).
            try:
                from app.core.config import DATA_DIR as _DATA_DIR
                crash_dir = _DATA_DIR / "logs"
            except Exception:
                # Fallback defensivo si config.py no se pudo cargar
                # (caso extremo: error muy temprano en el arranque).
                # Usamos la ruta relativa al archivo del módulo.
                from pathlib import Path
                crash_dir = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
            crash_dir.mkdir(parents=True, exist_ok=True)
            crash_log = open(crash_dir / "crash.log", "a", encoding="utf-8", buffering=1)
            crash_log.write(
                f"\n{'='*60}\nfaulthandler armado: "
                f"{__import__('datetime').datetime.now().isoformat()}\n{'='*60}\n"
            )
            crash_log.flush()
            _fh.enable(file=crash_log)
            # Guardamos referencia para que el archivo no se cierre
            install_global_exception_hooks._crash_log = crash_log
        except Exception as e:
            sys.stderr.write(f"No se pudo abrir crash.log: {e}\n")
    except Exception:
        pass

    _installed = True
    logger.info("Excepthooks globales instalados.")


# ──────────────────────────────────────────────────────────────
# Utilidades para callbacks defensivos
# ──────────────────────────────────────────────────────────────
def is_qt_alive(obj) -> bool:
    """
    Verifica si un objeto Qt (QWidget, QDialog, etc.) sigue siendo
    válido en el lado C++.

    Útil para callbacks asíncronos cuyo receptor pudo haber sido
    destruido entre que se lanzó el request y que llegó la respuesta
    (ej. usuario cierra el diálogo antes de que termine el HTTP).
    """
    if obj is None:
        return False
    try:
        import shiboken6
        return shiboken6.isValid(obj)
    except Exception:
        # Si shiboken6 no está disponible o falla, asumir vivo
        # (degradación elegante).
        return True


def safe_slot(fn: Callable, *, widget=None, label: str = "") -> Callable:
    """
    Envuelve un callable para que NO crashee la app si lanza una
    excepción o si el widget asociado ya fue destruido.

    Uso típico en callbacks de HttpWorker / api_call:

        api_call(
            "get", url,
            on_success=safe_slot(self._on_data, widget=self,
                                 label="cargar productos"),
            on_error=safe_slot(self._show_error, widget=self,
                               label="mostrar error"),
        )

    Reglas:
      - Si `widget` se pasó y ya no es válido → no llama a fn (devuelve None).
      - Si fn lanza → loguea con stack, NO re-raise.
      - Si fn devuelve OK → propaga el valor.
      - Loguea entrada/salida a nivel DEBUG con marcadores ▶ / ◀ para
        trazabilidad fina (qué callback se invocó, cuál terminó). Esto
        es útil para diagnosticar crashes que ocurren dentro de Qt C++
        durante el procesamiento de un signal: el último ▶ sin su ◀
        identifica el callback culpable.
    """
    def _wrapped(*args, **kwargs):
        _label = label or getattr(fn, "__name__", "<lambda>")

        if widget is not None and not is_qt_alive(widget):
            logger.debug(
                "safe_slot: widget destruido, callback '%s' ignorado.", _label
            )
            return None

        # ▶ Entrada: imprimimos un marcador antes de invocar el callback.
        # Si la app crashea dentro del callback (incluso en código C++ de
        # Qt al tocar un widget), este log será la última pista del
        # callback que se estaba procesando.
        logger.debug("safe_slot ▶ %s", _label)
        try:
            result = fn(*args, **kwargs)
            logger.debug("safe_slot ◀ %s", _label)
            return result
        except Exception as e:
            logger.error(
                "safe_slot ✖ excepción en callback '%s': %s",
                _label, e, exc_info=True,
            )
            # No re-raise: eso reactivaría el bug original de cierre silencioso.
            return None

    return _wrapped