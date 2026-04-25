"""
app/einvoice/xsd_validator.py — Validación XSD offline para comprobantes electrónicos v4.4

Valida el XML generado contra los XML Schemas oficiales de Hacienda ANTES de firmar/enviar.
Si el XML no pasa validación, se evita gastar secuencias o enviar documentos inválidos.

USO:
    from app.einvoice.xsd_validator import validate_xml

    errors = validate_xml(xml_string, "FE")  # o "TE", "NC", "REP"
    if errors:
        raise ValueError(f"XML inválido: {errors}")

SETUP:
    1. Descargar los XSD de Hacienda y colocarlos en app/einvoice/schemas/V4.4/
    2. URLs:
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica.xsd
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/tiqueteElectronico.xsd
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaCreditoElectronica.xsd
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaDebitoElectronica.xsd
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaCompra.xsd
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaExportacion.xsd
       - https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/reciboElectronicoPago.xsd
"""
from __future__ import annotations

import os
import logging
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# FIX: La carpeta real es "V4.4" (mayúscula).  En Linux el
#      filesystem es case-sensitive y "v4.4" no la encontraba.
# ──────────────────────────────────────────────────────────────
XSD_BASE_DIR = Path(__file__).parent / "schemas" / "V4.4"

# Mapeo doc_type → nombre del archivo XSD
XSD_FILES = {
    "FE":  "facturaElectronica.xsd",
    "TE":  "tiqueteElectronico.xsd",
    "NC":  "notaCreditoElectronica.xsd",
    "ND":  "notaDebitoElectronica.xsd",
    "FEC": "facturaElectronicaCompra.xsd",
    "FEE": "facturaElectronicaExportacion.xsd",
    "REP": "reciboElectronicoPago.xsd",
}

# Cache de schemas compilados
_schema_cache: dict[str, Any] = {}

# Flag para saber si lxml está disponible
_LXML_AVAILABLE = False
try:
    from lxml import etree as lxml_etree
    _LXML_AVAILABLE = True
except ImportError:
    logger.warning(
        "lxml no está instalado. Validación XSD deshabilitada. "
        "Instalá con: pip install lxml"
    )


def _get_xsd_path(doc_type: str) -> Optional[Path]:
    """Retorna la ruta al archivo XSD para el tipo de documento dado."""
    filename = XSD_FILES.get(doc_type)
    if not filename:
        return None
    path = XSD_BASE_DIR / filename
    if not path.exists():
        return None
    return path


def _load_schema(doc_type: str):
    """Carga y cachea el XMLSchema compilado para un tipo de documento."""
    if doc_type in _schema_cache:
        return _schema_cache[doc_type]

    xsd_path = _get_xsd_path(doc_type)
    if not xsd_path:
        return None

    try:
        with open(xsd_path, "rb") as f:
            schema_doc = lxml_etree.parse(f)
        schema = lxml_etree.XMLSchema(schema_doc)
        _schema_cache[doc_type] = schema
        logger.info(f"XSD schema cargado para {doc_type}: {xsd_path}")
        return schema
    except Exception as e:
        logger.error(f"Error cargando XSD para {doc_type}: {e}")
        return None


def validate_xml(xml_string: str, doc_type: str) -> list[str]:
    """
    Valida un XML contra el XSD correspondiente.

    Args:
        xml_string: El XML como string (output de xml_builder_v44)
        doc_type: Tipo de documento ("FE", "TE", "NC", "ND", "REP", etc.)

    Returns:
        Lista de errores. Lista vacía = XML válido.
        Si lxml no está instalado o el XSD no existe, retorna lista vacía
        (validación deshabilitada, no bloquea el flujo).
    """
    if not _LXML_AVAILABLE:
        logger.debug("Validación XSD omitida: lxml no disponible")
        return []

    schema = _load_schema(doc_type)
    if schema is None:
        logger.debug(
            f"Validación XSD omitida para {doc_type}: "
            f"XSD no encontrado en {XSD_BASE_DIR}. "
            f"Descargalo de cdn.comprobanteselectronicos.go.cr"
        )
        return []

    try:
        xml_doc = lxml_etree.fromstring(xml_string.encode("utf-8"))
        is_valid = schema.validate(xml_doc)

        if is_valid:
            logger.debug("XML %s pasó validación XSD ✓", doc_type)
            return []

        errors = []
        for error in schema.error_log:
            errors.append(f"Línea {error.line}: {error.message}")

        logger.warning(f"XML {doc_type} falló validación XSD: {len(errors)} errores")
        for err in errors[:5]:  # Log solo los primeros 5
            logger.warning(f"  → {err}")

        return errors

    except lxml_etree.XMLSyntaxError as e:
        return [f"XML malformado: {e}"]
    except Exception as e:
        logger.error(f"Error inesperado en validación XSD: {e}")
        return [f"Error de validación: {e}"]


def is_validation_available(doc_type: str) -> bool:
    """Verifica si la validación XSD está disponible para un tipo de documento."""
    if not _LXML_AVAILABLE:
        return False
    return _get_xsd_path(doc_type) is not None


def get_validation_status() -> dict:
    """Retorna el estado de disponibilidad de validación para cada tipo de documento."""
    status = {
        "lxml_installed": _LXML_AVAILABLE,
        "xsd_directory": str(XSD_BASE_DIR),
        "xsd_directory_exists": XSD_BASE_DIR.exists(),
        "schemas": {},
    }
    for doc_type, filename in XSD_FILES.items():
        path = XSD_BASE_DIR / filename
        status["schemas"][doc_type] = {
            "filename": filename,
            "exists": path.exists(),
            "path": str(path),
        }
    return status