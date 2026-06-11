"""
ui/services/update_manager.py — Orquestación de actualizaciones (lado UI)

Este módulo es el "motor" que la UI usa para actualizar Violette POS. La
presentación (diálogo, chequeo al iniciar sesión, botón en Ajustes) vive en
la Fase 4 y se apoya en las tres funciones públicas de aquí:

    check_async(...)            → ¿hay una versión más nueva? (en background)
    download_async(...)         → descargar el instalador (en background)
    apply_update_and_exit(...)  → el "relevo": lanzar el instalador y cerrar

──────────────────────────────────────────────────────────────────────────
POR QUÉ check/download CORREN CON run_async (y NO con QThread)
──────────────────────────────────────────────────────────────────────────
Este proyecto sufrió crashes binarios ("access violation" en Windows) cada
vez que objetos Qt (QThread / QObject / Signals) cruzaban hilos. La solución
adoptada —documentada en ui/utils/http_worker.py— es ejecutar el trabajo de
red en un threading.Thread de Python PURO que NUNCA toca Qt, devolviendo el
resultado por callbacks en el hilo principal, mientras la UI bombea eventos
(sin aceptar input) para no congelarse.

Por eso aquí NO creamos un QThread ni Signals propios: reutilizamos
run_async(), el mismo helper que usa toda la app. check_update() y
download_update() (de app.services.updater) son funciones de red puras que
no tocan Qt, así que encajan perfecto en ese patrón.

──────────────────────────────────────────────────────────────────────────
POR QUÉ apply_update_and_exit USA os._exit(0)
──────────────────────────────────────────────────────────────────────────
Violette POS corre como UN SOLO proceso: el backend FastAPI/uvicorn vive en
un hilo daemon y la UI Qt en el hilo principal (ver launcher._start_backend /
_start_ui). Para que el instalador Inno pueda reemplazar ViolettePOS.exe y su
carpeta _internal\\, Windows necesita que ese proceso termine y libere el
bloqueo de los archivos.

Tras lanzar el instalador (desacoplado, vía updater.spawn_installer), cerramos
con os._exit(0): una salida DURA e inmediata que garantiza liberar el lock
del .exe sin que ningún hook de cierre lo retrase. Es seguro en este proyecto
porque:

  · No hay handlers atexit registrados en ningún módulo (verificado).
  · La cola offline NO vive en memoria: se persiste en la base de datos en
    cada operación/ciclo (app/services/offline_queue.py hace commit por
    iteración), así que un cierre abrupto no pierde comprobantes en cola.
  · SQLite corre en modo WAL, que es a prueba de cierres súbitos / cortes de
    energía (el próximo arranque recupera automáticamente). En MySQL, cerrar
    de golpe solo cae la conexión; el servidor queda íntegro.
  · El instalador NO toca la base de datos (violette_pos.db) ni el .env: solo
    reemplaza el binario y _internal\\, que el cierre del proceso libera.

Una salida "graciosa" (QApplication.quit y dejar que app.exec() retorne) sería
más elegante, pero si quedara vivo cualquier hilo no-daemon el proceso no
terminaría y el instalador se quedaría esperando con el .exe bloqueado. Para un
relevo de actualización, el determinismo de os._exit(0) es la opción correcta.
"""

from __future__ import annotations

import os
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Chequeo y descarga en segundo plano (patrón run_async, sin tocar Qt)
# ══════════════════════════════════════════════════════════════════════

def check_async(
    on_success: Callable[[dict], None],
    on_error: Optional[Callable[[str], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
) -> None:
    """Verifica si hay actualización, en segundo plano.

    on_success recibe el dict de updater.check_update(). check_update() es
    defensivo y NO lanza: el resultado (incluido cualquier error de red) viene
    dentro del dict (claves 'available', 'error', etc.), así que la lógica del
    diálogo se maneja siempre desde on_success. on_error queda como red de
    seguridad ante una excepción inesperada.
    """
    # Imports locales: evitan cargar PySide6 / el backend al importar este
    # módulo, y rompen posibles ciclos de import en el arranque.
    from ui.utils.http_worker import run_async
    from app.services.updater import check_update

    run_async(
        check_update,
        on_success=on_success,
        on_error=on_error,
        on_finished=on_finished,
    )


def download_async(
    on_success: Callable[[dict], None],
    on_error: Optional[Callable[[str], None]] = None,
    on_finished: Optional[Callable[[], None]] = None,
) -> None:
    """Descarga el instalador del último release, en segundo plano.

    on_success recibe el dict de updater.download_update() (claves
    'downloaded', 'path', 'verified', 'message', ...). La descarga puede pesar
    decenas de MB: durante ese tiempo la UI sigue pintando (cursor de espera)
    pero no acepta clicks, gracias al bombeo de eventos de run_async.
    """
    from ui.utils.http_worker import run_async
    from app.services.updater import download_update

    run_async(
        download_update,
        on_success=on_success,
        on_error=on_error,
        on_finished=on_finished,
    )


# ══════════════════════════════════════════════════════════════════════
# El "relevo": lanzar el instalador y cerrar el proceso
# ══════════════════════════════════════════════════════════════════════

def apply_update_and_exit(installer_path: str, app=None) -> bool:
    """Lanza el instalador y TERMINA el proceso para liberar el .exe.

    Debe llamarse desde el hilo principal (toca QApplication y cierra el
    proceso). El flujo típico desde el diálogo es:
        download_async(... on_success=lambda r: apply_update_and_exit(r["path"]))

    Returns:
        False si no se pudo lanzar el instalador (la app sigue viva, el
        llamador debe avisar al usuario). Si el lanzamiento tiene éxito, esta
        función NO retorna: cierra el proceso con os._exit(0).
    """
    from app.services.updater import spawn_installer  # mismo proceso

    if not installer_path or not os.path.exists(str(installer_path)):
        logger.error("apply_update_and_exit: instalador inexistente: %r", installer_path)
        return False

    if not spawn_installer(installer_path, silent=True):
        logger.error("apply_update_and_exit: spawn_installer falló; se cancela el relevo.")
        return False

    # Cierre VISIBLE de la UI (cosmético): que las ventanas desaparezcan de
    # forma intencional antes del hard-exit. Defensivo: si Qt no está
    # disponible (tests/headless) simplemente se omite.
    try:
        from PySide6.QtWidgets import QApplication
        app = app or QApplication.instance()
        if app is not None:
            app.closeAllWindows()
            app.processEvents()
    except Exception:
        pass

    logger.info(
        "Relevo iniciado: cerrando Violette POS para que el instalador "
        "reemplace los archivos. El instalador reabrirá la app actualizada."
    )

    # Vaciar buffers de logging antes de la salida dura.
    logging.shutdown()

    # Salida DURA: garantiza liberar el lock del .exe de inmediato. Ver el
    # docstring del módulo para por qué esto es seguro en este proyecto.
    os._exit(0)

    # Inalcanzable (os._exit no retorna); presente solo por claridad del tipo.
    return False