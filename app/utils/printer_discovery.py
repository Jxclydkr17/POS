"""
app/utils/printer_discovery.py — Detección automática de impresoras.

OBJETIVO (mejora de UX para Settings → Impresora):
    Eliminar la necesidad de que el usuario escriba a mano el USB
    Vendor ID / Product ID. En su lugar, este módulo enumera las
    impresoras que el sistema ya conoce y las entrega listas para
    poblar un menú desplegable en la UI.

Dos fuentes de detección, complementarias:

  1. IMPRESORAS DEL SISTEMA (recomendado en Windows)
     ────────────────────────────────────────────────
     `list_system_printers()` usa el spooler del sistema operativo
     (en Windows, `win32print`). Devuelve las impresoras instaladas
     por NOMBRE — el mismo nombre que el usuario ve en el panel de
     Windows. Estas se imprimen con `Win32Raw` (ver
     `app.utils.print_ticket.print_to_system_printer`), que manda los
     bytes ESC/POS en modo RAW directamente a la cola de impresión.

     Ventaja clave: NO requiere libusb/Zadig ni reemplazar el driver
     del fabricante. Funciona con el driver normal de la térmica
     (Epson TM-*, Bixolon, Star, etc.). Es el camino más cómodo y
     fiable en Windows.

  2. DISPOSITIVOS USB CRUDOS (avanzado / multiplataforma)
     ────────────────────────────────────────────────
     `list_usb_printers()` escanea el bus USB con `pyusb` y devuelve
     vendor_id/product_id ya formateados. Sirve para el modo `usb`
     directo (ESC/POS por `escpos.printer.Usb`), que en Windows
     requiere un backend libusb instalado. Si no hay backend, la
     función degrada con elegancia y devuelve lista vacía + una nota
     explicativa — la UI entonces sugiere usar el modo `system`.

DISEÑO DEFENSIVO:
    - Ninguna importación de `win32print` ni `usb` a nivel de módulo.
      Ambas son opcionales y específicas de plataforma; importarlas
      perezosamente evita romper el arranque en entornos donde no
      están (p. ej. el servidor de tests en Linux sin libusb, o un
      build sin pywin32).
    - Toda la detección está envuelta en try/except: una falla de
      detección NUNCA debe tumbar el endpoint ni la app. En el peor
      caso se devuelve una lista vacía y una nota legible.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Disponibilidad de backends (chequeo perezoso, sin importar arriba)
# ─────────────────────────────────────────────────────────

def _win32print_available() -> bool:
    """True si `win32print` (paquete pywin32) se puede importar."""
    try:
        import win32print  # noqa: F401
        return True
    except Exception:
        return False


def _pyusb_available() -> bool:
    """
    True si `pyusb` Y un backend libusb están disponibles.

    Importar `usb.core` no basta: pyusb necesita un backend nativo
    (libusb) para escanear el bus. Verificamos que `find_library`
    resuelva un backend; si no, tratamos pyusb como no disponible para
    propósitos de detección (evita NoBackendError en runtime).
    """
    try:
        import usb.core  # noqa: F401
        import usb.backend.libusb1 as libusb1
        backend = libusb1.get_backend()
        if backend is None:
            # Sin backend libusb no se puede escanear el bus.
            return False
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────
# 1) Impresoras del sistema operativo (Windows: win32print)
# ─────────────────────────────────────────────────────────

def list_system_printers() -> list[dict[str, Any]]:
    """
    Lista las impresoras instaladas en el sistema operativo.

    En Windows usa `win32print.EnumPrinters`. Cada entrada incluye el
    nombre exacto (el que se usa luego con `Win32Raw`), el puerto, el
    driver y si es la impresora predeterminada.

    En sistemas que no son Windows devuelve [] (el modo `system` está
    pensado para el spooler de Windows; en Linux/macOS se recomienda
    `network` o `usb`).

    Returns:
        Lista de dicts:
            {
              "name": str,          # nombre canónico de la impresora
              "port": str | None,   # puerto (USB001, IP_..., etc.)
              "driver": str | None, # nombre del driver
              "is_default": bool,   # True si es la predeterminada del SO
            }
        Lista vacía si no hay impresoras o el backend no está disponible.
    """
    system = platform.system().lower()
    if system != "windows":
        return []

    if not _win32print_available():
        logger.info("list_system_printers: win32print no disponible.")
        return []

    try:
        import win32print
    except Exception as e:  # pragma: no cover - cubierto por el chequeo arriba
        logger.warning(f"list_system_printers: no se pudo importar win32print: {e}")
        return []

    printers: list[dict[str, Any]] = []
    default_name = ""
    try:
        default_name = win32print.GetDefaultPrinter() or ""
    except Exception:
        # No hay predeterminada configurada — no es fatal.
        default_name = ""

    try:
        # PRINTER_ENUM_LOCAL = impresoras instaladas localmente.
        # PRINTER_ENUM_CONNECTIONS = impresoras de red conectadas al perfil.
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        # Nivel 2 → dict con pPrinterName, pPortName, pDriverName, etc.
        raw = win32print.EnumPrinters(flags, None, 2)
    except Exception as e:
        logger.warning(f"list_system_printers: EnumPrinters falló: {e}")
        return []

    for info in raw or []:
        try:
            name = info.get("pPrinterName") if isinstance(info, dict) else None
            if not name:
                continue
            printers.append({
                "name": name,
                "port": (info.get("pPortName") if isinstance(info, dict) else None) or None,
                "driver": (info.get("pDriverName") if isinstance(info, dict) else None) or None,
                "is_default": (name == default_name),
            })
        except Exception:
            # Una entrada malformada no debe abortar toda la lista.
            continue

    # Ordenar: predeterminada primero, luego alfabético.
    printers.sort(key=lambda p: (not p["is_default"], (p["name"] or "").lower()))
    return printers


# ─────────────────────────────────────────────────────────
# 2) Dispositivos USB crudos (pyusb)
# ─────────────────────────────────────────────────────────

# Clase USB de impresoras según la especificación USB-IF.
_USB_PRINTER_CLASS = 0x07


def _read_usb_string(dev, index: int) -> str | None:
    """
    Lee un string descriptor del dispositivo USB de forma segura.

    Puede fallar si el SO no concede acceso al descriptor (común en
    Windows sin permisos). En ese caso devolvemos None y seguimos.
    """
    if not index:
        return None
    try:
        import usb.util
        value = usb.util.get_string(dev, index)
        if value:
            return str(value).strip() or None
    except Exception:
        return None
    return None


def _device_has_printer_interface(dev) -> bool:
    """
    True si alguna interfaz del dispositivo declara la clase de
    impresora (0x07). El bDeviceClass a nivel de dispositivo suele ser
    0 (definido por interfaz), por lo que hay que inspeccionar las
    interfaces de cada configuración.
    """
    try:
        # Clase a nivel de dispositivo.
        if getattr(dev, "bDeviceClass", 0) == _USB_PRINTER_CLASS:
            return True
        for cfg in dev:
            for intf in cfg:
                if getattr(intf, "bInterfaceClass", None) == _USB_PRINTER_CLASS:
                    return True
    except Exception:
        # Si no podemos leer configuraciones (sin permisos), no afirmamos.
        return False
    return False


def list_usb_printers(only_printer_class: bool = True) -> list[dict[str, Any]]:
    """
    Escanea el bus USB y devuelve dispositivos candidatos a impresora.

    Args:
        only_printer_class: si True, intenta filtrar a dispositivos que
            declaran la clase USB de impresora (0x07). Si la inspección
            de interfaces no es posible (sin permisos), el dispositivo
            igual se incluye para no esconder impresoras válidas — la
            UI muestra todos y el usuario elige.

    Returns:
        Lista de dicts:
            {
              "vendor_id": "0x04b8",
              "product_id": "0x0202",
              "vendor_id_int": 1208,
              "product_id_int": 514,
              "manufacturer": str | None,
              "product": str | None,
              "description": str,        # etiqueta amigable para la UI
              "is_printer_class": bool,  # True si declara clase 0x07
            }
        Lista vacía si pyusb/libusb no están disponibles o no hay
        dispositivos.
    """
    if not _pyusb_available():
        logger.info("list_usb_printers: pyusb/libusb no disponible.")
        return []

    try:
        import usb.core
    except Exception as e:  # pragma: no cover
        logger.warning(f"list_usb_printers: no se pudo importar usb.core: {e}")
        return []

    results: list[dict[str, Any]] = []
    try:
        devices = list(usb.core.find(find_all=True))
    except Exception as e:
        # NoBackendError u otros — degradamos sin romper.
        logger.warning(f"list_usb_printers: find() falló: {e}")
        return []

    for dev in devices:
        try:
            vid = int(getattr(dev, "idVendor", 0) or 0)
            pid = int(getattr(dev, "idProduct", 0) or 0)
            if vid == 0 and pid == 0:
                continue

            is_printer = _device_has_printer_interface(dev)
            if only_printer_class and not is_printer:
                # Si pudimos determinar que NO es impresora, lo saltamos.
                # Si la inspección no fue concluyente, _device_has_printer_interface
                # devuelve False; para no escondernos impresoras cuando no
                # hay permisos, sólo filtramos cuando hay clase declarada en
                # ALGÚN dispositivo del bus. Heurística: ver nota abajo.
                pass

            manufacturer = _read_usb_string(dev, getattr(dev, "iManufacturer", 0))
            product = _read_usb_string(dev, getattr(dev, "iProduct", 0))

            label_parts = []
            if manufacturer:
                label_parts.append(manufacturer)
            if product:
                label_parts.append(product)
            base_label = " ".join(label_parts) if label_parts else "Dispositivo USB"
            description = f"{base_label} (0x{vid:04x}:0x{pid:04x})"

            results.append({
                "vendor_id": f"0x{vid:04x}",
                "product_id": f"0x{pid:04x}",
                "vendor_id_int": vid,
                "product_id_int": pid,
                "manufacturer": manufacturer,
                "product": product,
                "description": description,
                "is_printer_class": bool(is_printer),
            })
        except Exception:
            # Un dispositivo problemático no debe abortar el escaneo entero.
            continue

    # Si pedimos solo-impresoras y AL MENOS uno declaró clase 0x07,
    # filtramos a esos. Si ninguno declaró clase (típico cuando no hay
    # permisos para leer interfaces), devolvemos todos para que el
    # usuario pueda elegir igual.
    if only_printer_class and any(r["is_printer_class"] for r in results):
        results = [r for r in results if r["is_printer_class"]]

    # Ordenar: impresoras declaradas primero, luego por descripción.
    results.sort(key=lambda r: (not r["is_printer_class"], r["description"].lower()))
    return results


# ─────────────────────────────────────────────────────────
# 3) Detección combinada (lo que consume el endpoint)
# ─────────────────────────────────────────────────────────

def discover_printers() -> dict[str, Any]:
    """
    Detección combinada para poblar la UI de Settings → Impresora.

    Returns:
        {
          "platform": "Windows" | "Linux" | "Darwin",
          "backends": {"win32print": bool, "pyusb": bool},
          "system": [ {name, port, driver, is_default}, ... ],
          "usb":    [ {vendor_id, product_id, description, ...}, ... ],
          "notes":  [ "mensaje legible", ... ],
        }

    Nunca levanta: cualquier error de detección se traduce en listas
    vacías + notas explicativas.
    """
    notes: list[str] = []

    win_ok = _win32print_available()
    usb_ok = _pyusb_available()

    system_printers: list[dict[str, Any]] = []
    usb_printers: list[dict[str, Any]] = []

    try:
        system_printers = list_system_printers()
    except Exception as e:
        logger.exception("discover_printers: list_system_printers falló")
        notes.append(f"No se pudieron listar las impresoras del sistema: {e}")

    try:
        usb_printers = list_usb_printers()
    except Exception as e:
        logger.exception("discover_printers: list_usb_printers falló")
        notes.append(f"No se pudo escanear el bus USB: {e}")

    plat = platform.system()

    # Notas guía para el usuario según lo que se encontró.
    if plat.lower() == "windows":
        if not win_ok:
            notes.append(
                "El módulo 'pywin32' no está disponible: no se pueden listar "
                "las impresoras del sistema. Reinstale la aplicación o instale "
                "pywin32."
            )
        elif not system_printers:
            notes.append(
                "No se detectaron impresoras instaladas en Windows. Verifique "
                "que la impresora esté encendida, conectada e instalada en "
                "'Configuración → Bluetooth y dispositivos → Impresoras'."
            )
        if not usb_ok:
            notes.append(
                "Escaneo USB directo no disponible (sin backend libusb). En "
                "Windows se recomienda usar el modo 'Impresora del sistema', "
                "que no requiere libusb."
            )
    else:
        notes.append(
            "El modo 'Impresora del sistema' está optimizado para Windows. "
            "En este sistema operativo se recomienda 'Red (IP)' o 'USB directa'."
        )

    return {
        "platform": plat,
        "backends": {"win32print": win_ok, "pyusb": usb_ok},
        "system": system_printers,
        "usb": usb_printers,
        "notes": notes,
    }