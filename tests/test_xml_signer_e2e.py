# tests/test_xml_signer_e2e.py
"""
Test end-to-end de la firma XAdES-EPES SIN credenciales de Hacienda.

Verifica el pipeline completo que Hacienda valida del lado del servidor, salvo
la comprobación de que el certificado provenga de la CA del MEIC (eso exige un
.p12 real). Aquí generamos un certificado autofirmado RSA-2048 al vuelo.

Cubre dos garantías críticas:

  1. EQUIVALENCIA c14n2 ↔ exc-c14n
     El firmador (app/einvoice/xml_signer.py) declara el algoritmo exc-c14n
     (http://www.w3.org/2001/10/xml-exc-c14n#) pero canonicaliza internamente con
     lxml method="c14n2". Si esos dos algoritmos NO produjeran bytes idénticos,
     Hacienda recalcularía los digests con exc-c14n y la firma fallaría.
     Estos tests recalculan cada digest y la firma RSA usando exc-c14n VERDADERO
     (method="c14n") y verifican que coinciden con lo que generó el firmador.

  2. VALIDEZ XSD del comprobante FIRMADO
     El XML firmado se valida contra el esquema oficial v4.4 (que incluye el
     esquema de ds:Signature). Esto confirma que el nodo de firma queda bien
     formado y en la posición correcta dentro del comprobante.

Si estos tests fallan, es señal de que Hacienda rechazaría los comprobantes.
"""

import os
import sys
import copy
import base64
import hashlib
import datetime
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

# Reutilizamos los mocks del test del builder (mismo directorio).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_xml_builder_v44 as B  # noqa: E402

try:
    from lxml import etree as LET
    _LXML = True
except ImportError:
    _LXML = False

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives.serialization import pkcs12
    _CRYPTO = True
except ImportError:
    _CRYPTO = False

pytestmark = pytest.mark.skipif(
    not (_LXML and _CRYPTO),
    reason="Requiere lxml y cryptography para el test de firma.",
)

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
XSD_DIR = Path(__file__).resolve().parents[1] / "app" / "einvoice" / "schemas" / "V4.4"


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _make_self_signed_p12(path: str, password: str):
    """Genera un .p12 autofirmado RSA-2048 válido por 10 años."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CR"),
        x509.NameAttribute(NameOID.COMMON_NAME, "CPF-01-1234-5678"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    with open(path, "wb") as f:
        f.write(pkcs12.serialize_key_and_certificates(
            name=b"test", key=key, cert=cert, cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
        ))
    return cert


def _true_exc_c14n(node) -> bytes:
    """Exclusive C14N 1.0 VERDADERO — el algoritmo que el XML declara."""
    return LET.tostring(node, method="c14n", exclusive=True, with_comments=False)


def _digest_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _build_signed_fe() -> tuple[str, object]:
    """Construye una FE real, la firma, y devuelve (xml_firmado, cert)."""
    from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44
    from app.einvoice.xml_signer import sign_xml

    db = B._mock_db()
    sale = B._mock_sale(document_type="01")
    details = [B._mock_detail(1), B._mock_detail(2)]
    customer = B._mock_customer()
    xml = build_xml_for_sale_v44(
        db, sale=sale, sale_details=details,
        clave="50601032500310123456700100001010000000001119283746",
        consecutivo="00100001010000000001",
        customer=customer,
    )

    tmpdir = tempfile.mkdtemp()
    p12_path = os.path.join(tmpdir, "test.p12")
    password = "secret123"
    cert = _make_self_signed_p12(p12_path, password)
    signed = sign_xml(xml, p12_path, password)
    return signed, cert


def _validate_against_xsd(xml_string: str, xsd_filename: str) -> list:
    xsd_path = XSD_DIR / xsd_filename
    if not xsd_path.exists():
        pytest.skip(f"XSD no encontrado: {xsd_path}")
    schema = LET.XMLSchema(LET.parse(str(xsd_path)))
    doc = LET.fromstring(xml_string.encode("utf-8"))
    if schema.validate(doc):
        return []
    return [f"L{e.line}: {e.message}" for e in schema.error_log]


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────
class TestXadesSignature:

    def test_signed_fe_has_signature_node(self):
        signed, _ = _build_signed_fe()
        doc = LET.fromstring(signed.encode("utf-8"))
        sig = doc.find(f"{{{NS_DS}}}Signature")
        assert sig is not None, "El XML firmado debe contener ds:Signature"

    def test_signed_fe_passes_official_xsd(self):
        """El comprobante FIRMADO debe validar contra el XSD oficial v4.4."""
        signed, _ = _build_signed_fe()
        errors = _validate_against_xsd(signed, "facturaElectronica.xsd")
        assert errors == [], f"Errores XSD en FE firmada: {errors[:5]}"

    def test_document_digest_matches_true_exc_c14n(self):
        """
        El digest del documento (Reference URI="") generado con c14n2 debe
        coincidir con el que Hacienda calcula usando exc-c14n verdadero:
        quitar ds:Signature (transform XPath) y canonicalizar.
        """
        signed, _ = _build_signed_fe()
        doc = LET.fromstring(signed.encode("utf-8"))
        sig = doc.find(f"{{{NS_DS}}}Signature")
        refs = sig.find(f"{{{NS_DS}}}SignedInfo").findall(f"{{{NS_DS}}}Reference")

        doc_no_sig = copy.deepcopy(doc)
        for s in doc_no_sig.findall(f"{{{NS_DS}}}Signature"):
            doc_no_sig.remove(s)

        expected = _digest_b64(_true_exc_c14n(doc_no_sig))
        stored = refs[0].find(f"{{{NS_DS}}}DigestValue").text
        assert stored == expected, (
            "El digest del documento no coincide con exc-c14n verdadero → "
            "Hacienda rechazaría la firma."
        )

    def test_signed_properties_digest_matches_true_exc_c14n(self):
        """El digest de SignedProperties debe coincidir con exc-c14n verdadero."""
        signed, _ = _build_signed_fe()
        doc = LET.fromstring(signed.encode("utf-8"))
        sig = doc.find(f"{{{NS_DS}}}Signature")
        refs = sig.find(f"{{{NS_DS}}}SignedInfo").findall(f"{{{NS_DS}}}Reference")

        sp_id = refs[1].get("URI").lstrip("#")
        signed_props = None
        for el in sig.iter(f"{{{NS_XADES}}}SignedProperties"):
            if el.get("Id") == sp_id:
                signed_props = el
                break
        assert signed_props is not None, f"No se encontró SignedProperties Id={sp_id}"

        expected = _digest_b64(_true_exc_c14n(signed_props))
        stored = refs[1].find(f"{{{NS_DS}}}DigestValue").text
        assert stored == expected, (
            "El digest de SignedProperties no coincide con exc-c14n verdadero."
        )

    def test_signature_value_verifies_with_true_exc_c14n(self):
        """
        La firma RSA-SHA256 sobre SignedInfo debe verificar cuando el verificador
        canonicaliza SignedInfo con exc-c14n verdadero (lo que hace Hacienda).
        """
        signed, cert = _build_signed_fe()
        doc = LET.fromstring(signed.encode("utf-8"))
        sig = doc.find(f"{{{NS_DS}}}Signature")
        signed_info = sig.find(f"{{{NS_DS}}}SignedInfo")
        sig_value = base64.b64decode(sig.find(f"{{{NS_DS}}}SignatureValue").text)

        si_c14n = _true_exc_c14n(signed_info)
        # No debe lanzar InvalidSignature
        cert.public_key().verify(
            sig_value, si_c14n, padding.PKCS1v15(), hashes.SHA256()
        )