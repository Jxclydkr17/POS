"""
app/einvoice/xml_signer.py — Firma XAdES-EPES para comprobantes electrónicos v4.4

Implementa firma digital XAdES-EPES ENVELOPED según los requerimientos del
Ministerio de Hacienda de Costa Rica (Anexo 2, versión 4.4):

  - Estándar: ETSI TS 101 903 v1.3.2+
  - Empaquetado: ENVELOPED
  - Algoritmos: RSA 2048/4096 + SHA-256
  - Canonicalización: Exclusive C14n (http://www.w3.org/2001/10/xml-exc-c14n#)
  - Policy: URL de la resolución de Hacienda

USO:
    from app.einvoice.xml_signer import sign_xml, load_certificate, get_cert_info

    # Firmar un XML
    xml_firmado = sign_xml(xml_string, "/path/to/cert.p12", "password")

    # Verificar certificado
    info = get_cert_info("/path/to/cert.p12", "password")

DEPENDENCIAS:
    pip install lxml cryptography
"""
from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import Certificate

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Constantes según Anexo 2, v4.4
# ═══════════════════════════════════════════════════════════════

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
NS_MAP_SIG = {"ds": NS_DS}
NS_MAP_XADES = {"xades": NS_XADES, "ds": NS_DS}

ALG_C14N_EXC = "http://www.w3.org/2001/10/xml-exc-c14n#"
ALG_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ALG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ALG_XPATH = "http://www.w3.org/TR/1999/REC-xpath-19991116"

POLICY_URL = (
    "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/"
    "Resoluci%C3%B3n_General_sobre_disposiciones_t%C3%A9cnicas_"
    "comprobantes_electr%C3%B3nicos_para_efectos_tributarios.pdf"
)
# Hash SHA-256 del PDF de la política (fijo, proporcionado por Hacienda)
POLICY_HASH = "DWxin1xWOeI8OuWQXazh4VjLWAaCLAA954em7DMh0h8="


# ═══════════════════════════════════════════════════════════════
# Carga de certificados .p12
# ═══════════════════════════════════════════════════════════════

def load_certificate(cert_path: str, cert_pass: str) -> tuple:
    """
    Carga un certificado PKCS#12 (.p12) y retorna (private_key, certificate, chain).

    Args:
        cert_path: Ruta al archivo .p12
        cert_pass: Contraseña del certificado

    Returns:
        Tupla (private_key, certificate, additional_certs)

    Raises:
        FileNotFoundError: Si el archivo no existe
        ValueError: Si la contraseña es incorrecta o el formato es inválido
    """
    path = Path(cert_path)
    if not path.exists():
        raise FileNotFoundError(f"Certificado no encontrado: {cert_path}")

    with open(path, "rb") as f:
        p12_data = f.read()

    try:
        private_key, certificate, chain = pkcs12.load_key_and_certificates(
            p12_data, cert_pass.encode("utf-8")
        )
    except Exception as e:
        raise ValueError(f"Error cargando certificado .p12: {e}")

    if private_key is None:
        raise ValueError("El archivo .p12 no contiene clave privada.")
    if certificate is None:
        raise ValueError("El archivo .p12 no contiene certificado.")

    return private_key, certificate, chain


def get_cert_info(cert_path: str, cert_pass: str) -> dict:
    """
    Retorna información del certificado sin exponer la clave privada.
    Útil para diagnóstico y validación de vigencia.
    """
    private_key, cert, chain = load_certificate(cert_path, cert_pass)

    now = datetime.now(timezone.utc)
    not_before = cert.not_valid_before_utc if hasattr(cert, 'not_valid_before_utc') else cert.not_valid_before.replace(tzinfo=timezone.utc)
    not_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after.replace(tzinfo=timezone.utc)

    days_remaining = (not_after - now).days

    key_size = private_key.key_size if hasattr(private_key, "key_size") else "unknown"

    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "serial_number": cert.serial_number,
        "not_valid_before": not_before.isoformat(),
        "not_valid_after": not_after.isoformat(),
        "days_remaining": days_remaining,
        "is_valid": not_before <= now <= not_after,
        "is_expiring_soon": 0 < days_remaining <= 30,
        "key_size": key_size,
        "chain_certs": len(chain) if chain else 0,
    }


# ═══════════════════════════════════════════════════════════════
# Helpers internos
# ═══════════════════════════════════════════════════════════════

def _c14n_exc(node: etree._Element) -> bytes:
    """Canonicaliza un nodo con Exclusive C14n."""
    return etree.tostring(node, method="c14n2", exclusive=True, with_comments=False)


def _digest_sha256(data: bytes) -> str:
    """SHA-256 digest, retorna base64."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _cert_der_b64(cert: Certificate) -> str:
    """Certificado X.509 en DER, codificado en base64 (sin line breaks)."""
    der = cert.public_bytes(serialization.Encoding.DER)
    return base64.b64encode(der).decode("ascii")


def _cert_digest_sha256(cert: Certificate) -> str:
    """SHA-256 del certificado en DER, retorna base64."""
    der = cert.public_bytes(serialization.Encoding.DER)
    return base64.b64encode(hashlib.sha256(der).digest()).decode("ascii")


def _cert_issuer_name(cert: Certificate) -> str:
    """Nombre del emisor del certificado en formato RFC4514."""
    return cert.issuer.rfc4514_string()


def _cert_serial(cert: Certificate) -> str:
    """Número de serie del certificado como string decimal."""
    return str(cert.serial_number)


def _make_id() -> str:
    """Genera un ID único para los elementos de la firma."""
    return uuid.uuid4().hex


def _sign_rsa_sha256(private_key, data: bytes) -> bytes:
    """Firma datos con RSA-SHA256 (PKCS#1 v1.5)."""
    return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())


# ═══════════════════════════════════════════════════════════════
# Construcción de la firma XAdES-EPES
# ═══════════════════════════════════════════════════════════════

def _build_signed_properties(
    sig_id: str,
    cert: Certificate,
    signing_time: str,
) -> etree._Element:
    """
    Construye el nodo xades:SignedProperties con:
    - SigningTime
    - SigningCertificate (digest del certificado)
    - SignaturePolicyIdentifier (política de Hacienda)
    - SignedDataObjectProperties (MimeType)
    """
    xades_sp = etree.Element(
        f"{{{NS_XADES}}}SignedProperties",
        attrib={"Id": f"xades-{sig_id}"},
        nsmap=NS_MAP_XADES,
    )

    # ── SignedSignatureProperties ──
    ssp = etree.SubElement(xades_sp, f"{{{NS_XADES}}}SignedSignatureProperties")

    # SigningTime
    st = etree.SubElement(ssp, f"{{{NS_XADES}}}SigningTime")
    st.text = signing_time

    # SigningCertificate
    sc = etree.SubElement(ssp, f"{{{NS_XADES}}}SigningCertificate")
    sc_cert = etree.SubElement(sc, f"{{{NS_XADES}}}Cert")

    cd = etree.SubElement(sc_cert, f"{{{NS_XADES}}}CertDigest")
    cd_method = etree.SubElement(cd, f"{{{NS_DS}}}DigestMethod",
                                 attrib={"Algorithm": ALG_SHA256})
    cd_value = etree.SubElement(cd, f"{{{NS_DS}}}DigestValue")
    cd_value.text = _cert_digest_sha256(cert)

    iss = etree.SubElement(sc_cert, f"{{{NS_XADES}}}IssuerSerial")
    iss_name = etree.SubElement(iss, f"{{{NS_DS}}}X509IssuerName")
    iss_name.text = _cert_issuer_name(cert)
    iss_serial = etree.SubElement(iss, f"{{{NS_DS}}}X509SerialNumber")
    iss_serial.text = _cert_serial(cert)

    # SignaturePolicyIdentifier
    spi = etree.SubElement(ssp, f"{{{NS_XADES}}}SignaturePolicyIdentifier")
    sp_id_node = etree.SubElement(spi, f"{{{NS_XADES}}}SignaturePolicyId")

    sig_pol_id = etree.SubElement(sp_id_node, f"{{{NS_XADES}}}SigPolicyId")
    identifier = etree.SubElement(sig_pol_id, f"{{{NS_XADES}}}Identifier")
    identifier.text = POLICY_URL

    sig_pol_hash = etree.SubElement(sp_id_node, f"{{{NS_XADES}}}SigPolicyHash")
    hash_method = etree.SubElement(sig_pol_hash, f"{{{NS_DS}}}DigestMethod",
                                   attrib={"Algorithm": ALG_SHA256})
    hash_value = etree.SubElement(sig_pol_hash, f"{{{NS_DS}}}DigestValue")
    hash_value.text = POLICY_HASH

    # ── SignedDataObjectProperties ──
    sdop = etree.SubElement(xades_sp, f"{{{NS_XADES}}}SignedDataObjectProperties")
    dof = etree.SubElement(sdop, f"{{{NS_XADES}}}DataObjectFormat",
                           attrib={"ObjectReference": "#r-id-1"})
    mime = etree.SubElement(dof, f"{{{NS_XADES}}}MimeType")
    mime.text = "application/octet-stream"

    return xades_sp


def sign_xml(xml_str: str, cert_path: str, cert_pass: str) -> str:
    """
    Firma un XML con XAdES-EPES ENVELOPED según los requerimientos de Hacienda CR.

    Args:
        xml_str: XML sin firmar (output de xml_builder_v44)
        cert_path: Ruta al archivo .p12
        cert_pass: Contraseña del certificado

    Returns:
        XML firmado como string UTF-8

    Raises:
        FileNotFoundError: Si el certificado no existe
        ValueError: Si el certificado es inválido o ha expirado
    """
    # 1. Cargar certificado
    private_key, cert, chain = load_certificate(cert_path, cert_pass)

    # Verificar vigencia
    now = datetime.now(timezone.utc)
    not_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after.replace(tzinfo=timezone.utc)
    not_before = cert.not_valid_before_utc if hasattr(cert, 'not_valid_before_utc') else cert.not_valid_before.replace(tzinfo=timezone.utc)

    if now > not_after:
        raise ValueError(
            f"El certificado expiró el {not_after.isoformat()}. "
            "Renová tu certificado en el ATV o con tu banco."
        )
    if now < not_before:
        raise ValueError(f"El certificado aún no es válido (válido desde {not_before.isoformat()}).")

    # 2. Parsear el XML con lxml
    doc = etree.fromstring(xml_str.encode("utf-8"))

    # 3. IDs únicos para la firma
    sig_id = _make_id()

    # 4. Signing time en UTC ISO 8601
    signing_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 5. Digest del contenido del documento (SIN Signature)
    #    Canonicalización exc-c14n del root element completo
    doc_c14n = _c14n_exc(doc)
    doc_digest = _digest_sha256(doc_c14n)

    # 6. Construir SignedProperties y calcular su digest
    signed_props = _build_signed_properties(sig_id, cert, signing_time)
    sp_c14n = _c14n_exc(signed_props)
    sp_digest = _digest_sha256(sp_c14n)

    # 7. Construir SignedInfo con ambas References
    signed_info = etree.Element(f"{{{NS_DS}}}SignedInfo", nsmap=NS_MAP_SIG)

    c14n_method = etree.SubElement(signed_info, f"{{{NS_DS}}}CanonicalizationMethod",
                                   attrib={"Algorithm": ALG_C14N_EXC})
    sig_method = etree.SubElement(signed_info, f"{{{NS_DS}}}SignatureMethod",
                                  attrib={"Algorithm": ALG_RSA_SHA256})

    # Reference 1: Contenido del documento
    ref1 = etree.SubElement(signed_info, f"{{{NS_DS}}}Reference",
                            attrib={"Id": "r-id-1", "Type": "", "URI": ""})
    transforms1 = etree.SubElement(ref1, f"{{{NS_DS}}}Transforms")

    # Transform: XPath que excluye ds:Signature
    t_xpath = etree.SubElement(transforms1, f"{{{NS_DS}}}Transform",
                               attrib={"Algorithm": ALG_XPATH})
    xpath_el = etree.SubElement(t_xpath, f"{{{NS_DS}}}XPath")
    xpath_el.text = "not(ancestor-or-self::ds:Signature)"

    # Transform: Exclusive C14n
    etree.SubElement(transforms1, f"{{{NS_DS}}}Transform",
                     attrib={"Algorithm": ALG_C14N_EXC})

    dm1 = etree.SubElement(ref1, f"{{{NS_DS}}}DigestMethod",
                           attrib={"Algorithm": ALG_SHA256})
    dv1 = etree.SubElement(ref1, f"{{{NS_DS}}}DigestValue")
    dv1.text = doc_digest

    # Reference 2: SignedProperties (XAdES)
    ref2 = etree.SubElement(signed_info, f"{{{NS_DS}}}Reference",
                            attrib={
                                "Type": "http://uri.etsi.org/01903#SignedProperties",
                                "URI": f"#xades-{sig_id}",
                            })
    transforms2 = etree.SubElement(ref2, f"{{{NS_DS}}}Transforms")
    etree.SubElement(transforms2, f"{{{NS_DS}}}Transform",
                     attrib={"Algorithm": ALG_C14N_EXC})
    dm2 = etree.SubElement(ref2, f"{{{NS_DS}}}DigestMethod",
                           attrib={"Algorithm": ALG_SHA256})
    dv2 = etree.SubElement(ref2, f"{{{NS_DS}}}DigestValue")
    dv2.text = sp_digest

    # 8. Canonicalizar SignedInfo y firmar
    si_c14n = _c14n_exc(signed_info)
    signature_value_bytes = _sign_rsa_sha256(private_key, si_c14n)
    signature_value_b64 = base64.b64encode(signature_value_bytes).decode("ascii")

    # 9. Ensamblar el nodo ds:Signature completo
    sig_element = etree.Element(
        f"{{{NS_DS}}}Signature",
        attrib={"Id": f"id-{sig_id}"},
        nsmap=NS_MAP_SIG,
    )

    # SignedInfo
    sig_element.append(signed_info)

    # SignatureValue
    sv = etree.SubElement(sig_element, f"{{{NS_DS}}}SignatureValue",
                          attrib={"Id": f"valueid{sig_id}"})
    sv.text = signature_value_b64

    # KeyInfo con certificado X.509
    ki = etree.SubElement(sig_element, f"{{{NS_DS}}}KeyInfo")
    x509_data = etree.SubElement(ki, f"{{{NS_DS}}}X509Data")
    x509_cert = etree.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate")
    x509_cert.text = _cert_der_b64(cert)

    # Object con QualifyingProperties
    obj = etree.SubElement(sig_element, f"{{{NS_DS}}}Object")
    qp = etree.SubElement(obj, f"{{{NS_XADES}}}QualifyingProperties",
                          attrib={"Target": f"#id-{sig_id}"},
                          nsmap=NS_MAP_XADES)
    qp.append(signed_props)

    # 10. Insertar ds:Signature como último hijo del root
    doc.append(sig_element)

    # 11. Serializar
    result = etree.tostring(doc, encoding="utf-8", xml_declaration=True)
    return result.decode("utf-8")


# ═══════════════════════════════════════════════════════════════
# Utilidades de diagnóstico
# ═══════════════════════════════════════════════════════════════

def is_signing_available(cert_path: Optional[str], cert_pass: Optional[str]) -> dict:
    """
    Verifica si la firma digital está disponible y el certificado es válido.
    Retorna un dict con el estado para mostrar en la UI.
    """
    result = {
        "available": False,
        "cert_path": cert_path,
        "error": None,
    }

    if not cert_path or not cert_pass:
        result["error"] = "HACIENDA_CERT_PATH o HACIENDA_CERT_PASS no configurados en .env"
        return result

    try:
        info = get_cert_info(cert_path, cert_pass)
        result.update(info)
        result["available"] = info["is_valid"]
        if not info["is_valid"]:
            result["error"] = "Certificado expirado o aún no válido"
        elif info["is_expiring_soon"]:
            result["error"] = f"Certificado expira en {info['days_remaining']} días"
    except FileNotFoundError:
        result["error"] = f"Archivo no encontrado: {cert_path}"
    except ValueError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"Error inesperado: {e}"

    return result