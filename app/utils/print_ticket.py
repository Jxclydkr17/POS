"""
app/utils/print_ticket.py — Impresión de tickets y comprobantes

Soporta:
  1. Impresión via sistema operativo (Windows/Mac/Linux) → funciona OK.
  2. Envío RAW de bytes por TCP/IP (utility de bajo nivel para ESC/POS).
  3. Flujo integrado con facturación electrónica.

⚠️  FASE 2 — Fix 2.5: Impresión térmica directa NO está implementada
   Las impresoras térmicas POS (Epson TM-T20, Bixolon SRP-275, etc.)
   hablan ESC/POS, NO PDF. Enviar bytes PDF al puerto 9100 produce
   caracteres aleatorios impresos o cuelga la impresora.

   Antes este archivo abría el PDF, leía sus bytes y los enviaba a la
   térmica. Esa vía está deshabilitada (`use_thermal=True` ahora lanza
   NotImplementedError) hasta que se implemente generación de comandos
   ESC/POS con python-escpos u otra librería equivalente.

   Mientras tanto use el flujo por SO (use_thermal=False, default), que
   imprime el PDF via `os.startfile(file, "print")` en Windows
   (`lp`/`lpr` en macOS/Linux) y sí funciona con cualquier impresora.

USO:
    from app.utils.print_ticket import print_pdf
    print_pdf("/ruta/al/comprobante.pdf")  # Imprime via SO (funciona)
"""

import os
import platform
import subprocess
import socket
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def print_pdf(file_path: str) -> None:
    """
    Imprime un archivo PDF usando el sistema operativo.

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


def print_to_thermal(
    data: bytes,
    ip: str = "192.168.0.120",
    port: int = 9100,
    timeout: int = 5,
) -> None:
    """
    Utility de bajo nivel: envía bytes RAW a un puerto TCP (típicamente 9100
    de una impresora térmica).

    ⚠️  FASE 2 — Fix 2.5:
       Esta función NO interpreta su entrada. `data` debe ser una secuencia
       de comandos ESC/POS o texto plano que la impresora térmica entienda.
       NO pasar bytes PDF: las térmicas POS no interpretan PDF y producen
       caracteres aleatorios o se cuelgan.

       Hoy nada en la app llama esta función con bytes válidos para POS
       (no hay generador ESC/POS implementado todavía). Queda como
       primitiva para una futura integración con python-escpos.

    Args:
        data: Bytes ESC/POS o texto plano (NO PDF).
        ip: Dirección IP de la impresora.
        port: Puerto TCP (default 9100 = "RAW printing" estándar).
        timeout: Timeout de conexión en segundos.

    Raises:
        ConnectionError: Si no se puede conectar a la impresora.
        RuntimeError: Si falla el envío.
    """
    try:
        logger.info(f"Conectando a impresora térmica {ip}:{port}...")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            s.sendall(data)

        logger.info(f"Datos enviados a impresora térmica ({len(data)} bytes)")

    except socket.timeout:
        raise ConnectionError(
            f"Timeout conectando a impresora {ip}:{port}. "
            "Verifique que la impresora esté encendida y accesible."
        )
    except ConnectionRefusedError:
        raise ConnectionError(
            f"Conexión rechazada por {ip}:{port}. "
            "Verifique la IP y que la impresora esté en modo RAW."
        )
    except Exception as e:
        raise RuntimeError(f"Error enviando a impresora térmica: {e}")


def print_einvoice_ticket(
    db,
    einvoice_id: int,
    *,
    use_thermal: bool = False,
    thermal_ip: str | None = None,
    thermal_port: int | None = None,
) -> str:
    """
    Genera el PDF del comprobante electrónico y lo imprime.

    Flujo integrado:
    1. Genera PDF con QR via einvoice_pdf service
    2. Imprime via sistema operativo (siempre, ver nota)

    ⚠️  FASE 2 — Fix 2.5:
       `use_thermal=True` ahora lanza NotImplementedError. La vía vieja
       enviaba bytes PDF al puerto 9100 — eso corrompe el output de las
       impresoras térmicas POS (no entienden PDF, solo ESC/POS). Use el
       flujo SO (use_thermal=False, default) hasta que se implemente la
       generación ESC/POS con python-escpos u otra librería.

    Args:
        db: Sesión de BD
        einvoice_id: ID del ElectronicInvoice
        use_thermal: DEBE ser False. True levanta NotImplementedError.
        thermal_ip: (reservado para futuro) IP de impresora térmica
        thermal_port: (reservado para futuro) Puerto de impresora térmica

    Returns:
        Ruta del PDF generado.

    Raises:
        NotImplementedError: Si use_thermal=True.
    """
    from app.services.einvoice_pdf import generate_einvoice_pdf
    from app.core.config import get_logo_path

    # Buscar logo (ruta absoluta portable para .exe)
    logo = get_logo_path()

    # Generar PDF
    pdf_path = generate_einvoice_pdf(db, einvoice_id, logo_path=logo)

    # ── FASE 2 — Fix 2.5: la vía térmica directa está deshabilitada ──
    # Antes acá se hacía: leer pdf_path como bytes, mandárselos al puerto
    # 9100 con print_to_thermal(). Eso es CORROMPER el output: las térmicas
    # POS (Epson TM-T20, Bixolon, Star TSP, etc.) hablan ESC/POS, no PDF.
    # El comentario viejo "la mayoría de impresoras térmicas modernas
    # aceptan PDF vía RAW" es FALSO. Solo impresoras de oficina con
    # interpretación PJL/PostScript aceptan PDF crudo.
    #
    # Hasta que se implemente generación ESC/POS (con python-escpos u
    # otra librería), bloqueamos esta vía con un error claro en lugar
    # de basura impresa o impresora colgada.
    if use_thermal:
        # Aunque thermal_ip/thermal_port se sigan resolviendo y leyendo de
        # settings, NO los usamos para enviar PDF crudo. Mejor un error claro.
        raise NotImplementedError(
            "Impresión directa a impresora térmica POS no está implementada "
            "todavía: requiere generar comandos ESC/POS, no enviar PDF crudo "
            "al puerto 9100 (eso produce caracteres aleatorios impresos o "
            "cuelga la impresora). Use la impresión vía sistema operativo "
            "(use_thermal=False, el default), que abre el PDF en el flujo "
            "de impresión del SO y funciona con cualquier impresora."
        )

    # Imprimir via sistema operativo (vía que SÍ funciona)
    print_pdf(pdf_path)

    return pdf_path