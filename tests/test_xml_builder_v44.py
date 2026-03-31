"""
tests/test_xml_builder_v44.py — Tests del XML builder contra XSD v4.4

Valida que los XML generados por el builder pasen la validación
contra los XSD oficiales de Hacienda descargados en schemas/V4.4/.

USO:
    pytest tests/test_xml_builder_v44.py -v

Estos tests usan mocks en vez de una BD real para que corran rápido
y sin dependencia de MySQL.
"""

import sys
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from decimal import Decimal

# Asegurar que el proyecto esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Verificar que lxml esté disponible ──
try:
    from lxml import etree as lxml_etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

# XSD directory
XSD_DIR = Path(__file__).resolve().parents[1] / "app" / "einvoice" / "schemas" / "V4.4"


# ══════════════════════════════════════════════════════════════
# Helpers: Mock objects que simulan los modelos SQLAlchemy
# ══════════════════════════════════════════════════════════════

def _mock_issuer(**overrides):
    """Crea un IssuerProfile mock con todos los campos requeridos."""
    defaults = {
        "id": 1,
        "legal_name": "EMPRESA DE PRUEBAS S.A.",
        "commercial_name": "PRUEBAS COMERCIAL",
        "id_type": "02",
        "id_number": "3101234567",
        "email": "test@test.com",
        "phone": "88887777",
        "phone_country_code": "506",
        "provider_system_id": "ViolettePOS",
        "economic_activity_code": "523400",
        "provincia": "1",
        "canton": "01",
        "distrito": "01",
        "barrio": "01",
        "otras_senas": "100 metros al norte del parque central",
        "branch_code": "001",
        "terminal_code": "00001",
        "enable_rep": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_customer(**overrides):
    """Crea un Customer mock."""
    defaults = {
        "id": 1,
        "name": "CLIENTE DE PRUEBA",
        "id_type": "01",
        "id_number": "123456789",
        "email": "cliente@test.com",
        "phone": "87654321",
        "address": "San José Centro",
        "province_id": "1",
        "province_name": "San José",
        "canton_id": "01",
        "canton_name": "San José",
        "district_id": "01",
        "district_name": "Carmen",
        "barrio": "01",
        "otras_senas": "Frente al correo",
        "economic_activity_code": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_sale(**overrides):
    """Crea un Sale mock."""
    defaults = {
        "id": 1,
        "customer_id": 1,
        "document_type": "04",
        "payment_method": "efectivo",
        "total": 11300.0,
        "condicion_venta_code": "01",
        "condicion_venta_otros": None,
        "moneda_code": "CRC",
        "tipo_cambio": "1",
        "status": "ACTIVA",
        "credit_days": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_detail(idx=1, **overrides):
    """Crea un SaleDetail mock."""
    defaults = {
        "id": idx,
        "sale_id": 1,
        "product_id": idx,
        "quantity": Decimal("2"),
        "unit_price": Decimal("5000.00"),
        "discount_percent": Decimal("0"),
        "subtotal": Decimal("10000.00"),
        "tax_rate": 13.0,
        "tax_amount": Decimal("1300.00000"),
        "is_common": False,
        "common_description": None,
        "discount_code": None,
        "discount_code_otro": None,
        "discount_description": None,
        "tipo_transaccion": None,
        "iva_cobrado_fabrica": None,
        "numero_vin_serie": None,
        "impuesto_code": None,
        "factor_calculo_iva": None,
        "exon_tipo_doc": None,
        "exon_tipo_doc_otro": None,
        "exon_numero_doc": None,
        "exon_articulo": None,
        "exon_inciso": None,
        "exon_institucion": None,
        "exon_institucion_otro": None,
        "exon_fecha": None,
        "exon_tarifa": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_product(idx=1, **overrides):
    """Crea un Product mock."""
    defaults = {
        "id": idx,
        "code": f"P{idx:04d}",
        "name": f"Producto de prueba #{idx}",
        "cabys_code": "4322200000000",
        "tax_rate": 13.0,
        "unit_type": "Unid",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_db(issuer=None, product=None):
    """Crea un mock de sesión de BD que retorna el issuer y product."""
    db = MagicMock()

    iss = issuer or _mock_issuer()
    prod = product or _mock_product()

    # db.query(IssuerProfile).order_by(...).first() → issuer
    query_mock = MagicMock()
    order_mock = MagicMock()
    order_mock.first.return_value = iss
    query_mock.order_by.return_value = order_mock

    # db.query(Product).filter(...).first() → product
    filter_mock = MagicMock()
    filter_mock.first.return_value = prod
    query_mock.filter.return_value = filter_mock

    db.query.return_value = query_mock

    return db


def _validate_against_xsd(xml_string: str, xsd_filename: str) -> list[str]:
    """Valida un XML contra un XSD y retorna lista de errores."""
    if not HAS_LXML:
        pytest.skip("lxml no instalado")

    xsd_path = XSD_DIR / xsd_filename
    if not xsd_path.exists():
        pytest.skip(f"XSD no encontrado: {xsd_path}")

    with open(xsd_path, "rb") as f:
        schema_doc = lxml_etree.parse(f)
    schema = lxml_etree.XMLSchema(schema_doc)

    xml_doc = lxml_etree.fromstring(xml_string.encode("utf-8"))
    is_valid = schema.validate(xml_doc)

    if is_valid:
        return []

    # ds:Signature is added post-build by xml_signer.sign_xml(), so ignore its absence
    return [
        f"Línea {e.line}: {e.message}"
        for e in schema.error_log
        if "Signature" not in e.message
    ]


# ══════════════════════════════════════════════════════════════
# Tests: Tiquete Electrónico (TE - doc_type "04")
# ══════════════════════════════════════════════════════════════

class TestTiqueteElectronico:
    """Tests para generación de Tiquete Electrónico."""

    def test_te_generates_valid_xml(self):
        """Un TE básico debe generar XML bien formado."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="04")
        details = [_mock_detail(1)]

        xml = build_xml_for_sale_v44(
            db, sale=sale, sale_details=details,
            clave="50601032500310123456700100001040000000001119283746",
            consecutivo="00100001040000000001",
        )

        assert xml is not None
        assert "TiqueteElectronico" in xml
        assert "50601032500310123456700100001040000000001119283746" in xml

    def test_te_passes_xsd_validation(self):
        """El TE generado debe pasar validación XSD."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="04")
        details = [_mock_detail(1)]

        xml = build_xml_for_sale_v44(
            db, sale=sale, sale_details=details,
            clave="50601032500310123456700100001040000000001119283746",
            consecutivo="00100001040000000001",
        )

        errors = _validate_against_xsd(xml, "tiqueteElectronico.xsd")
        assert errors == [], f"XSD errors: {errors[:5]}"

    def test_te_without_customer(self):
        """TE debe funcionar sin cliente (cliente general)."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="04")
        details = [_mock_detail(1)]

        xml = build_xml_for_sale_v44(
            db, sale=sale, sale_details=details,
            clave="50601032500310123456700100001040000000001119283746",
            consecutivo="00100001040000000001",
            customer=None,
        )

        assert "TiqueteElectronico" in xml


# ══════════════════════════════════════════════════════════════
# Tests: Factura Electrónica (FE - doc_type "01")
# ══════════════════════════════════════════════════════════════

class TestFacturaElectronica:
    """Tests para generación de Factura Electrónica."""

    def test_fe_generates_valid_xml(self):
        """Una FE básica con receptor debe generar XML bien formado."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="01")
        details = [_mock_detail(1)]
        customer = _mock_customer()

        xml = build_xml_for_sale_v44(
            db, sale=sale, sale_details=details,
            clave="50601032500310123456700100001010000000001119283746",
            consecutivo="00100001010000000001",
            customer=customer,
        )

        assert "FacturaElectronica" in xml
        assert "CLIENTE DE PRUEBA" in xml

    def test_fe_passes_xsd_validation(self):
        """La FE generada debe pasar validación XSD."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="01")
        details = [_mock_detail(1)]
        customer = _mock_customer()

        xml = build_xml_for_sale_v44(
            db, sale=sale, sale_details=details,
            clave="50601032500310123456700100001010000000001119283746",
            consecutivo="00100001010000000001",
            customer=customer,
        )

        errors = _validate_against_xsd(xml, "facturaElectronica.xsd")
        assert errors == [], f"XSD errors: {errors[:5]}"

    def test_fe_requires_customer(self):
        """FE sin receptor debe fallar con ValueError."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="01")
        details = [_mock_detail(1)]

        with pytest.raises(ValueError, match="receptor"):
            build_xml_for_sale_v44(
                db, sale=sale, sale_details=details,
                clave="50601032500310123456700100001010000000001119283746",
                consecutivo="00100001010000000001",
                customer=None,
            )

    def test_fe_multiple_lines(self):
        """FE con múltiples líneas de detalle."""
        from app.einvoice.xml_builder_v44 import build_xml_for_sale_v44

        db = _mock_db()
        sale = _mock_sale(document_type="01", total=33900.0)
        details = [
            _mock_detail(1, quantity=Decimal("3"), subtotal=Decimal("15000.00"), tax_amount=Decimal("1950.00000")),
            _mock_detail(2, quantity=Decimal("1"), unit_price=Decimal("15000.00"), subtotal=Decimal("15000.00"), tax_amount=Decimal("1950.00000")),
        ]
        customer = _mock_customer()

        xml = build_xml_for_sale_v44(
            db, sale=sale, sale_details=details,
            clave="50601032500310123456700100001010000000002119283746",
            consecutivo="00100001010000000002",
            customer=customer,
        )

        assert "FacturaElectronica" in xml
        # Debe tener 2 LineaDetalle
        assert xml.count("<NumeroLinea>") == 2


# ══════════════════════════════════════════════════════════════
# Tests: MensajeReceptor
# ══════════════════════════════════════════════════════════════

class TestMensajeReceptor:
    """Tests para el builder de MensajeReceptor v4.4."""

    def test_mensaje_aceptado(self):
        """MensajeReceptor de aceptación genera XML válido."""
        from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

        xml = build_mensaje_receptor(
            clave_comprobante="50601032500310123456700100001040000000001119283746",
            cedula_emisor="3101234567",
            mensaje=1,
            cedula_receptor="3109876543",
            consecutivo_receptor="00100001050000000001",
            total_factura=11300.00,
            detalle_mensaje="Comprobante aceptado",
        )

        assert "MensajeReceptor" in xml
        assert "50601032500310123456700100001040000000001119283746" in xml

    def test_mensaje_rechazado_requiere_detalle(self):
        """Rechazo sin detalle debe fallar."""
        from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

        with pytest.raises(ValueError, match="DetalleMensaje"):
            build_mensaje_receptor(
                clave_comprobante="50601032500310123456700100001040000000001119283746",
                cedula_emisor="3101234567",
                mensaje=3,
                cedula_receptor="3109876543",
                consecutivo_receptor="00100001070000000001",
                total_factura=11300.00,
                detalle_mensaje="",  # vacío = error
            )

    def test_mensaje_con_campos_v44(self):
        """MensajeReceptor con campos v4.4 (actividad, condición impuesto, montos)."""
        from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

        xml = build_mensaje_receptor(
            clave_comprobante="50601032500310123456700100001040000000001119283746",
            cedula_emisor="3101234567",
            mensaje=1,
            cedula_receptor="3109876543",
            consecutivo_receptor="00100001050000000001",
            total_factura=11300.00,
            detalle_mensaje="Aceptado con crédito fiscal",
            monto_total_impuesto=1300.00,
            codigo_actividad="523400",
            condicion_impuesto="01",
            monto_impuesto_acreditar=1300.00,
            monto_gasto_aplicable=0,
        )

        assert "CodigoActividad" in xml
        assert "CondicionImpuesto" in xml
        assert "MontoTotalImpuestoAcreditar" in xml
        assert "MontoTotalDeGastoAplicable" in xml

    def test_mensaje_passes_xsd_validation(self):
        """MensajeReceptor debe pasar validación XSD."""
        from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

        xml = build_mensaje_receptor(
            clave_comprobante="50601032500310123456700100001040000000001119283746",
            cedula_emisor="3101234567",
            mensaje=1,
            cedula_receptor="3109876543",
            consecutivo_receptor="00100001050000000001",
            total_factura=11300.00,
            detalle_mensaje="Aceptado",
            monto_total_impuesto=1300.00,
            codigo_actividad="523400",
            condicion_impuesto="01",
            monto_impuesto_acreditar=1300.00,
            monto_gasto_aplicable=0,
        )

        errors = _validate_against_xsd(xml, "mensajeReceptor.xsd")
        assert errors == [], f"XSD errors: {errors[:5]}"

    def test_mensaje_clave_invalida(self):
        """Clave con longitud incorrecta debe fallar."""
        from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

        with pytest.raises(ValueError, match="50 dígitos"):
            build_mensaje_receptor(
                clave_comprobante="12345",
                cedula_emisor="3101234567",
                mensaje=1,
                cedula_receptor="3109876543",
                consecutivo_receptor="00100001050000000001",
                total_factura=100.00,
            )

    def test_mensaje_condicion_impuesto_invalida(self):
        """CondicionImpuesto con código inválido debe fallar."""
        from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

        with pytest.raises(ValueError, match="CondicionImpuesto"):
            build_mensaje_receptor(
                clave_comprobante="50601032500310123456700100001040000000001119283746",
                cedula_emisor="3101234567",
                mensaje=1,
                cedula_receptor="3109876543",
                consecutivo_receptor="00100001050000000001",
                total_factura=100.00,
                condicion_impuesto="99",  # inválido
            )


# ══════════════════════════════════════════════════════════════
# Tests: Validaciones de la clave y consecutivo
# ══════════════════════════════════════════════════════════════

class TestClaveConsecutivo:
    """Tests para generación de clave y consecutivo."""

    def test_build_consecutivo(self):
        """Consecutivo debe tener 20 dígitos."""
        from app.einvoice.sequence import build_consecutivo

        c = build_consecutivo("001", "00001", "04", 1)
        assert len(c) == 20
        assert c == "00100001040000000001"

    def test_build_clave(self):
        """Clave debe tener 50 dígitos."""
        from app.einvoice.sequence import build_clave

        clave = build_clave("3101234567", "00100001040000000001")
        assert len(clave) == 50
        assert clave.isdigit()
        assert clave.startswith("506")

    def test_normalize_document_type(self):
        """Tipo de documento debe normalizarse a 2 dígitos."""
        from app.einvoice.sequence import normalize_document_type

        assert normalize_document_type("1") == "01"
        assert normalize_document_type("04") == "04"
        assert normalize_document_type("10") == "10"

    def test_normalize_document_type_invalid(self):
        """Tipo de documento inválido debe fallar."""
        from app.einvoice.sequence import normalize_document_type

        with pytest.raises(ValueError):
            normalize_document_type("abc")

        with pytest.raises(ValueError):
            normalize_document_type("123")