"""
app/utils/print_ticket.py — Impresión de tickets y comprobantes

Soporta:
  1. Impresión directa a impresora térmica por red (TCP/IP)
  2. Impresión via sistema operativo (Windows/Mac/Linux)
  3. Flujo integrado con facturación electrónica

FASE 3 FIX:
  - Conectado al flujo de factura electrónica
  - Soporta impresión de PDF de comprobante con QR
  - Lee configuración de impresora desde settings de BD

USO:
    from app.utils.print_ticket import print_pdf, print_to_thermal

    # Imprimir PDF via SO
    print_pdf("/ruta/al/comprobante.pdf")

    # Imprimir directo a térmica
    print_to_thermal(raw_bytes, ip="192.168.0.120", port=9100)
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
    Envía datos RAW directamente a una impresora térmica por TCP/IP.

    Args:
        data: Bytes a enviar (ESC/POS commands o texto plano).
        ip: Dirección IP de la impresora.
        port: Puerto (default 9100 = RAW printing).
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
    2. Imprime via SO o impresora térmica según configuración

    Args:
        db: Sesión de BD
        einvoice_id: ID del ElectronicInvoice
        use_thermal: Si True, envía a impresora térmica
        thermal_ip: IP de la impresora (override)
        thermal_port: Puerto de la impresora (override)

    Returns:
        Ruta del PDF generado.
    """
    from app.services.einvoice_pdf import generate_einvoice_pdf

    # Buscar logo
    logo = None
    for candidate in ["ui/assets/logoferre.jpg", "ui/assets/logo.png"]:
        if os.path.exists(candidate):
            logo = candidate
            break

    # Generar PDF
    pdf_path = generate_einvoice_pdf(db, einvoice_id, logo_path=logo)

    # Leer configuración de impresora desde settings si no se pasa override
    if use_thermal:
        if not thermal_ip or not thermal_port:
            try:
                from app.db.models.settings import Settings
                settings_row = db.query(Settings).filter(Settings.id == 1).first()
                if settings_row:
                    thermal_ip = thermal_ip or settings_row.printer_ip or "192.168.0.120"
                    thermal_port = thermal_port or settings_row.printer_port or 9100
                else:
                    thermal_ip = thermal_ip or "192.168.0.120"
                    thermal_port = thermal_port or 9100
            except Exception:
                thermal_ip = thermal_ip or "192.168.0.120"
                thermal_port = thermal_port or 9100

        # Para impresora térmica, enviamos el PDF como archivo
        # (la mayoría de impresoras térmicas modernas aceptan PDF vía RAW)
        with open(pdf_path, "rb") as f:
            print_to_thermal(f.read(), ip=thermal_ip, port=thermal_port)
    else:
        # Imprimir via sistema operativo
        print_pdf(pdf_path)

    return pdf_path