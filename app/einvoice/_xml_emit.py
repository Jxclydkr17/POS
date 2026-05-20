# app/einvoice/_xml_emit.py
"""
FASE 4.2 — Fix 4.2: Serialización XML con declaración estándar.

`xml.etree.ElementTree.tostring(..., xml_declaration=True)` emite la
declaración con comillas SIMPLES:
    <?xml version='1.0' encoding='utf-8'?>

Mientras XML 1.0 acepta ambos tipos de comillas, varios validadores
estrictos (XSD validators, herramientas de terceros, algunos
verificadores de Hacienda) esperan comillas DOBLES — que es lo que
genera lxml y la mayoría del ecosistema XML.

Este módulo provee dos helpers que producen la forma estándar:
    <?xml version="1.0" encoding="UTF-8"?>

`xml_to_bytes(root)` → bytes con declaración + body.
`xml_to_str(root)`   → str con declaración + body.

No tocan el cuerpo del XML (sigue siendo idéntico a lo que produce
ET.tostring sin declaración).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'


def xml_to_bytes(root: ET.Element) -> bytes:
    """Serializa el árbol como bytes con declaración estándar."""
    body = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return _DECLARATION + body


def xml_to_str(root: ET.Element) -> str:
    """Serializa el árbol como str con declaración estándar."""
    return xml_to_bytes(root).decode("utf-8")