"""
app/utils/print_ticket.py — Impresión de tickets y comprobantes

Soporta tres caminos de impresión:
  1. PDF via sistema operativo (Windows/Mac/Linux) — funciona OK con
     cualquier impresora reconocida por el SO.
  2. ESC/POS via TCP a impresora térmica de red (puerto 9100 RAW).
  3. ESC/POS via USB a impresora térmica conectada localmente.

FASE 2 — Fix 2.5 (cerrado):
   La vía vieja "PDF crudo al puerto 9100" sigue prohibida (las térmicas
   POS no interpretan PDF, producen caracteres aleatorios o se cuelgan).
   Lo que SÍ hacemos ahora: generamos comandos ESC/POS con python-escpos
   (módulo `app.utils.escpos_ticket`) y los enviamos por TCP o USB.

   Esto cierra el Fix 2.5: antes la deuda era "los hooks están listos
   pero falta el generador". Ahora el generador existe, así que
   `use_thermal=True` funciona de verdad en lugar de levantar
   NotImplementedError.

USO:
    # PDF via SO (sigue funcionando como respaldo universal)
    from app.utils.print_ticket import print_pdf
    print_pdf("/ruta/al/comprobante.pdf")

    # ESC/POS via red (impresora térmica IP)
    from app.utils.print_ticket import print_to_thermal
    from app.utils.escpos_ticket import build_sale_ticket_bytes
    data = build_sale_ticket_bytes(sale_data, business_name="Mi Negocio")
    print_to_thermal(data, ip="192.168.0.120", port=9100)

    # ESC/POS via USB
    from app.utils.print_ticket import print_to_thermal_usb
    print_to_thermal_usb(data, vendor_id=0x04b8, product_id=0x0202)
"""

from __future__ import annotations

import os
import platform
import subprocess
import socket
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
# Camino 1 — PDF via sistema operativo (respaldo universal)
# ═════════════════════════════════════════════════════════════

def print_pdf(file_path: str) -> None:
    """
    Imprime un archivo PDF usando el sistema operativo.

    En Windows usa `os.startfile(path, "print")`, que abre el handler
    de impresión asociado al PDF (Adobe Reader, SumatraPDF, Edge, etc.)
    y dispara el envío a la impresora predeterminada del SO.
    En macOS/Linux usa `lp`/`lpr`.

    Esto SIEMPRE funciona — independiente de si la impresora es
    térmica, láser, de oficina, en red o por USB — porque depende del
    driver instalado en el SO, no de hablar ESC/POS directamente.

    Args:
        file_path: Ruta al archivo PDF a imprimir.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        RuntimeError: Si la impresión falla.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No se encontró el archivo: {file_path}")

    try:
        system = platform.system().lower()
        logger.info(f"Imprimiendo PDF: {file_path} (OS: {system})")

        if system == "windows":
            os.startfile(file_path, "print")
        elif system == "darwin":  # macOS
            subprocess.run(["lp", file_path], check=True)
        else:  # Linux
            subprocess.run(["lpr", file_path], check=True)

        logger.info(f"PDF enviado a impresora: {Path(file_path).name}")

    except Exception as e:
        raise RuntimeError(f"Error al imprimir el archivo: {e}")


# ═════════════════════════════════════════════════════════════
# Camino 2 — ESC/POS via TCP/IP (RAW puerto 9100)
# ═════════════════════════════════════════════════════════════

def print_to_thermal(
    data: bytes,
    ip: str = "192.168.0.120",
    port: int = 9100,
    timeout: int = 5,
) -> None:
    """
    Envía bytes ESC/POS a una impresora térmica en red.

    ⚠️  PRECONDICIÓN: `data` DEBE ser una secuencia válida de comandos
        ESC/POS (o texto que la térmica entienda). Si pasás bytes PDF
        acá, la impresora va a escupir basura o colgarse (las POS no
        interpretan PDF). Para generar bytes ESC/POS válidos usá
        `app.utils.escpos_ticket.build_sale_ticket_bytes` o
        `build_einvoice_ticket_bytes`.

    El puerto 9100 es el estándar "RAW printing" de impresoras de red.
    Casi todas las térmicas POS modernas (Epson TM-T20/T82/T88, Bixolon
    SRP-275/350, Star TSP-100, etc.) lo soportan.

    Args:
        data: Bytes ESC/POS o texto plano (NO PDF).
        ip: Dirección IP de la impresora.
        port: Puerto TCP (default 9100).
        timeout: Timeout de conexión en segundos.

    Raises:
        ConnectionError: Si no se puede conectar a la impresora.
        RuntimeError: Si falla el envío.
    """
    if not data:
        raise ValueError("`data` está vacío. Nada para enviar.")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(
            f"`data` debe ser bytes (got {type(data).__name__}). "
            "Use app.utils.escpos_ticket para generar comandos ESC/POS."
        )

    try:
        logger.info(f"Conectando a impresora térmica {ip}:{port}...")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            s.sendall(data)

        logger.info(f"ESC/POS enviado a {ip}:{port} ({len(data)} bytes)")

    except socket.timeout:
        raise ConnectionError(
            f"Timeout conectando a impresora {ip}:{port}. "
            "Verifique que la impresora esté encendida y accesible en la red."
        )
    except ConnectionRefusedError:
        raise ConnectionError(
            f"Conexión rechazada por {ip}:{port}. "
            "Verifique la IP, que la impresora esté en modo RAW y "
            "que el puerto 9100 esté habilitado."
        )
    except OSError as e:
        # OSError abarca: red caída, host inalcanzable, etc.
        raise ConnectionError(f"Error de red comunicando con {ip}:{port}: {e}")
    except Exception as e:
        raise RuntimeError(f"Error enviando a impresora térmica: {e}")


# ═════════════════════════════════════════════════════════════
# Camino 3 — ESC/POS via USB
# ═════════════════════════════════════════════════════════════

def print_to_thermal_usb(
    data: bytes,
    vendor_id: int,
    product_id: int,
    interface: int = 0,
    profile: Optional[str] = None,
    timeout_ms: int = 5000,
) -> None:
    """
    Envía bytes ESC/POS a una impresora térmica USB.

    Para conocer los vendor_id/product_id de tu impresora:
      - Linux: `lsusb` → "ID 04b8:0202" → vendor=0x04b8, product=0x0202
      - Windows: Administrador de dispositivos → Propiedades → Detalles
        → "Hardware Ids" → "USB\\VID_04B8&PID_0202"
      - macOS: System Information → USB

    Requiere `python-escpos` y `pyusb`. En Linux también requiere libusb
    y reglas udev (o ejecutar con sudo) para acceder al dispositivo USB.

    Args:
        data: Bytes ESC/POS.
        vendor_id: ID de fabricante (int, e.g. 0x04b8 para Epson).
        product_id: ID de producto (int, e.g. 0x0202).
        interface: Número de interfaz USB (default 0).
        profile: Perfil python-escpos opcional.
        timeout_ms: Timeout de I/O en milisegundos.

    Raises:
        RuntimeError: Si python-escpos o pyusb no están instalados,
            si el dispositivo no se encuentra, o si falla el envío.
    """
    if not data:
        raise ValueError("`data` está vacío. Nada para enviar.")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(
            f"`data` debe ser bytes (got {type(data).__name__}). "
            "Use app.utils.escpos_ticket para generar comandos ESC/POS."
        )

    # Importamos acá adentro porque pyusb es dependencia opcional
    # (solo necesaria para el camino USB). En despliegues sin USB
    # — i.e. impresora de red o solo SO — el módulo no debería romper
    # al cargar si pyusb no está instalado.
    try:
        from escpos.printer import Usb
    except ImportError as e:
        raise RuntimeError(
            "Para impresión USB se requieren `python-escpos` y `pyusb` "
            "instalados. Instale con: pip install python-escpos pyusb. "
            f"Detalle: {e}"
        )

    try:
        logger.info(
            f"Abriendo impresora USB vendor=0x{vendor_id:04x} "
            f"product=0x{product_id:04x} iface={interface}"
        )

        # python-escpos Usb maneja la apertura/cierre del device.
        # Pasamos `timeout` en ms (la lib lo acepta como kwarg).
        usb_kwargs = {"timeout": timeout_ms}
        if profile:
            usb_kwargs["profile"] = profile

        printer = Usb(vendor_id, product_id, interface, **usb_kwargs)
        try:
            # `_raw` es el escape hatch para enviar bytes ya armados,
            # sin pasar por la API de alto nivel (text/cut/etc). Como
            # nuestros bytes vienen de Dummy() ya tienen toda la
            # secuencia incluido el corte.
            printer._raw(bytes(data))
        finally:
            try:
                printer.close()
            except Exception:
                pass

        logger.info(f"ESC/POS enviado a USB {vendor_id:04x}:{product_id:04x} ({len(data)} bytes)")

    except Exception as e:
        # python-escpos puede levantar `USBNotFoundError` (subclass de
        # Exception). Normalizamos a RuntimeError para que el caller no
        # necesite conocer la jerarquía de la librería.
        raise RuntimeError(f"Error enviando a impresora USB: {e}")


# ═════════════════════════════════════════════════════════════
# Flujo integrado — comprobante electrónico (Hacienda CR)
# ═════════════════════════════════════════════════════════════

def print_einvoice_ticket(
    db,
    einvoice_id: int,
    *,
    use_thermal: bool = False,
    thermal_ip: Optional[str] = None,
    thermal_port: Optional[int] = None,
    thermal_usb_vendor_id: Optional[int] = None,
    thermal_usb_product_id: Optional[int] = None,
    thermal_kind: str = "network",
    paper_width_mm: int = 80,
    profile: Optional[str] = None,
) -> str:
    """
    Imprime un comprobante electrónico.

    Dos modos:
      - PDF via SO  (use_thermal=False, default): genera el PDF de
        representación gráfica y lo manda al spool del SO. Es la vía
        universal y la más robusta.
      - ESC/POS térmica directa (use_thermal=True): genera comandos
        ESC/POS para el ticket compacto y los manda por TCP o USB.

    Fase 2 — Fix 2.5: antes la vía térmica leía los bytes del PDF y los
    enviaba al puerto 9100, lo cual produce basura impresa o cuelga la
    impresora. Eso quedó eliminado. Hoy la vía térmica usa
    `app.utils.escpos_ticket.build_einvoice_ticket_bytes` para generar
    comandos válidos.

    Args:
        db: Sesión de SQLAlchemy.
        einvoice_id: ID del ElectronicInvoice a imprimir.
        use_thermal: True para vía ESC/POS directa, False para PDF via SO.
        thermal_ip / thermal_port: Para `thermal_kind="network"`.
        thermal_usb_vendor_id / thermal_usb_product_id: Para
            `thermal_kind="usb"`.
        thermal_kind: "network" o "usb" (solo aplica si use_thermal=True).
        paper_width_mm: 58 o 80 (solo aplica si use_thermal=True).
        profile: Nombre de perfil python-escpos (e.g. "TM-T20II").

    Returns:
        Ruta del PDF generado (siempre se genera el PDF, aunque se
        imprima por térmica, para que quede archivado y para visualizar
        desde la UI).

    Raises:
        ConnectionError / RuntimeError: si la térmica falla.
        ValueError: si faltan parámetros para el modo seleccionado.
    """
    from app.services.einvoice_pdf import generate_einvoice_pdf
    from app.core.config import get_logo_path

    # Generamos siempre el PDF (sirve de respaldo y para visualizar en UI).
    logo = get_logo_path()
    pdf_path = generate_einvoice_pdf(db, einvoice_id, logo_path=logo)

    if not use_thermal:
        # Camino estándar: PDF via SO.
        print_pdf(pdf_path)
        return pdf_path

    # ── Vía térmica directa ──
    from app.utils.escpos_ticket import build_einvoice_ticket_bytes

    data = build_einvoice_ticket_bytes(
        db, einvoice_id,
        paper_width_mm=paper_width_mm,
        cut=True,
        profile=profile,
    )

    kind = (thermal_kind or "network").lower()
    if kind == "network":
        if not thermal_ip:
            raise ValueError(
                "thermal_kind='network' requiere thermal_ip. "
                "Configure la IP en Settings → Impresora."
            )
        port = thermal_port or 9100
        print_to_thermal(data, ip=thermal_ip, port=port)
    elif kind == "usb":
        if thermal_usb_vendor_id is None or thermal_usb_product_id is None:
            raise ValueError(
                "thermal_kind='usb' requiere vendor_id y product_id. "
                "Configúrelos en Settings → Impresora."
            )
        print_to_thermal_usb(
            data,
            vendor_id=thermal_usb_vendor_id,
            product_id=thermal_usb_product_id,
            profile=profile,
        )
    else:
        raise ValueError(f"thermal_kind inválido: '{kind}'. Use 'network' o 'usb'.")

    return pdf_path


# ═════════════════════════════════════════════════════════════
# Helper de prueba — útil para el botón "Probar impresión" en UI
# ═════════════════════════════════════════════════════════════

def print_test_page(
    *,
    thermal_kind: str = "network",
    thermal_ip: Optional[str] = None,
    thermal_port: Optional[int] = None,
    thermal_usb_vendor_id: Optional[int] = None,
    thermal_usb_product_id: Optional[int] = None,
    paper_width_mm: int = 80,
    profile: Optional[str] = None,
) -> None:
    """
    Imprime una página de prueba ESC/POS corta a la impresora térmica
    configurada. Útil para validar IP/puerto/USB sin tener que armar
    una venta completa.

    Raises:
        ConnectionError / RuntimeError: si la impresión falla.
    """
    from escpos.printer import Dummy

    p = Dummy(profile=profile) if profile else Dummy()

    p.set(align="center", bold=True, double_height=True, double_width=True)
    p.text("PÁGINA DE PRUEBA\n")
    p.set(align="center", bold=False, double_height=False, double_width=False)
    p.text("Violette POS\n")
    p.text("-" * (32 if paper_width_mm == 58 else 48) + "\n")
    p.set(align="left")
    p.text("Si lee este texto, la impresora\nestá conectada correctamente.\n")
    p.text("\n")
    p.set(align="center")
    p.text("OK\n\n\n")
    try:
        p.cut()
    except Exception:
        pass

    data = p.output

    kind = (thermal_kind or "network").lower()
    if kind == "network":
        if not thermal_ip:
            raise ValueError("Configure la IP de la impresora en Settings → Impresora.")
        print_to_thermal(data, ip=thermal_ip, port=thermal_port or 9100)
    elif kind == "usb":
        if thermal_usb_vendor_id is None or thermal_usb_product_id is None:
            raise ValueError(
                "Configure vendor_id y product_id de la impresora USB en Settings → Impresora."
            )
        print_to_thermal_usb(
            data,
            vendor_id=thermal_usb_vendor_id,
            product_id=thermal_usb_product_id,
            profile=profile,
        )
    else:
        raise ValueError(f"thermal_kind inválido: '{kind}'. Use 'network' o 'usb'.")