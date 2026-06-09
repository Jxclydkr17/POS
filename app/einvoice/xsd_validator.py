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

import logging
import sys
from typing import Optional, Any
from pathlib import Path

from app.core.config import resolve_resource

logger = logging.getLogger(__name__)

# Namespace de la firma XML-DSig (para detectar/ignorar ds:Signature).
_NS_DS = "http://www.w3.org/2000/09/xmldsig#"


def _is_missing_signature_error(message: str) -> bool:
    """True si el error de XSD corresponde a la ausencia del nodo ds:Signature.

    El XSD oficial exige ds:Signature (minOccurs=1) como último hijo del
    comprobante. Cuando se valida el XML ANTES de firmar (dry-run), lxml
    reporta exactamente este error de completitud. Lo identificamos de forma
    conservadora: el mensaje debe mencionar 'Signature' Y ser un error de
    "falta un hijo"/"se esperaba". Cualquier otro error —aunque mencione
    Signature por casualidad— NO se ignora.
    """
    if not message or "Signature" not in message:
        return False
    return ("Missing child" in message) or ("Expected is" in message)


# True si corremos dentro del .exe empaquetado (PyInstaller).
_FROZEN = bool(getattr(sys, "frozen", False))

# ──────────────────────────────────────────────────────────────
# FIX: La carpeta real es "V4.4" (mayúscula).  En Linux el
#      filesystem es case-sensitive y "v4.4" no la encontraba.
#
# FASE 3 — Resolución consciente del empaquetado: en el .exe los XSD
# viven en _internal/app/einvoice/schemas/V4.4 (RESOURCE_DIR), no junto
# al ejecutable. resolve_resource() los busca ahí primero y, como red de
# seguridad, también junto al .exe (por si el usuario deja XSD nuevos de
# Hacienda sin recompilar). En desarrollo resuelve a la raíz del proyecto.
# El fallback a la ruta relativa al módulo cubre el caso degenerado en que
# resolve_resource no encuentre nada (entonces _get_xsd_path avisará).
# ──────────────────────────────────────────────────────────────
XSD_BASE_DIR = (
    resolve_resource("app/einvoice/schemas/V4.4")
    or (Path(__file__).parent / "schemas" / "V4.4")
)

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

# ── FASE 3 — Aviso ruidoso (no silencioso) cuando la validación se
# desactiva por falta de lxml o de los XSD. En un .exe empaquetado eso es
# un problema de despliegue real (se estaría firmando/enviando a Hacienda
# SIN validar localmente), así que se registra como ERROR; en desarrollo,
# como WARNING. Se avisa UNA sola vez por motivo para no inundar el log.
_unavailable_warned: set[str] = set()


def _warn_unavailable(reason_key: str, message: str) -> None:
    """Registra, UNA vez por motivo, que la validación XSD no está activa."""
    if reason_key in _unavailable_warned:
        return
    _unavailable_warned.add(reason_key)
    if _FROZEN:
        logger.error("VALIDACIÓN XSD DESACTIVADA — %s", message)
    else:
        logger.warning("Validación XSD desactivada — %s", message)


# Flag para saber si lxml está disponible
_LXML_AVAILABLE = False
try:
    from lxml import etree as lxml_etree
    _LXML_AVAILABLE = True
except ImportError:
    # Aviso inmediato y ruidoso (en frozen, ERROR) — sin lxml no hay
    # validación posible y los documentos saldrían sin verificar.
    _msg = ("lxml no está instalado: los comprobantes se firmarían/enviarían "
            "SIN validación XSD local. Instalá lxml (pip install lxml).")
    if bool(getattr(sys, "frozen", False)):
        logger.error("VALIDACIÓN XSD DESACTIVADA — %s", _msg)
    else:
        logger.warning("Validación XSD desactivada — %s", _msg)


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


def validate_xml(xml_string: str, doc_type: str, require_signature: bool = True) -> list[str]:
    """
    Valida un XML contra el XSD correspondiente.

    Args:
        xml_string: El XML como string (output de xml_builder_v44)
        doc_type: Tipo de documento ("FE", "TE", "NC", "ND", "REP", etc.)
        require_signature: Si True (por defecto), exige el nodo ds:Signature
            tal como manda el XSD oficial (minOccurs=1) — usar para validar el
            XML YA FIRMADO. Si False, se ignora ÚNICAMENTE el error de
            completitud por ausencia de ds:Signature, y solo cuando el
            documento todavía no tiene firma — usar para el "dry-run" del XML
            sin firmar, antes de gastar un consecutivo. Cualquier otro error
            estructural se reporta igual.

    Returns:
        Lista de errores. Lista vacía = XML válido.
        Si lxml no está instalado o el XSD no existe, retorna lista vacía
        (validación deshabilitada, no bloquea el flujo).
    """
    if not _LXML_AVAILABLE:
        _warn_unavailable(
            "lxml",
            "lxml no disponible; el XML se acepta SIN validar contra el XSD.",
        )
        return []

    schema = _load_schema(doc_type)
    if schema is None:
        _warn_unavailable(
            f"schema:{doc_type}",
            f"no se encontró/compiló el XSD de '{doc_type}' en {XSD_BASE_DIR}; "
            f"ese tipo de documento se acepta SIN validar. "
            f"Descargalo de cdn.comprobanteselectronicos.go.cr.",
        )
        return []

    try:
        xml_doc = lxml_etree.fromstring(xml_string.encode("utf-8"))
        is_valid = schema.validate(xml_doc)

        if is_valid:
            logger.debug("XML %s pasó validación XSD ✓", doc_type)
            return []

        # ── Validación en dos fases (require_signature) ──
        # El XSD oficial declara ds:Signature como obligatorio (minOccurs=1).
        # En el "dry-run" se valida el XML ANTES de firmar (xml_signer.sign_xml
        # agrega la firma después), por lo que el único error esperado y
        # legítimo en ese punto es la ausencia de ds:Signature. Con
        # require_signature=False se descarta EXCLUSIVAMENTE ese error de
        # completitud —y solo si el documento aún no tiene firma—, dejando
        # pasar cualquier otro error estructural del cuerpo.
        ignore_missing_sig = (not require_signature) and (
            xml_doc.find(f".//{{{_NS_DS}}}Signature") is None
        )

        errors = []
        for error in schema.error_log:
            if ignore_missing_sig and _is_missing_signature_error(error.message):
                continue
            errors.append(f"Línea {error.line}: {error.message}")

        if not errors:
            logger.debug(
                "XML %s válido salvo la firma (dry-run, require_signature=False) ✓",
                doc_type,
            )
            return []

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
        "frozen": _FROZEN,
        "xsd_directory": str(XSD_BASE_DIR),
        "xsd_directory_exists": Path(XSD_BASE_DIR).exists(),
        "schemas": {},
    }
    all_present = True
    for doc_type, filename in XSD_FILES.items():
        path = XSD_BASE_DIR / filename
        exists = path.exists()
        all_present = all_present and exists
        status["schemas"][doc_type] = {
            "filename": filename,
            "exists": exists,
            "path": str(path),
        }
    # Resumen de alto nivel: la validación está realmente ACTIVA solo si
    # lxml está instalado Y existen todos los XSD. Útil para que la pestaña
    # de diagnóstico muestre un estado claro en vez de inferirlo.
    status["all_schemas_present"] = all_present
    status["validation_active"] = bool(_LXML_AVAILABLE and all_present)
    return status