from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional, List
import xml.etree.ElementTree as ET

from sqlalchemy.orm import Session
from app.db.models.issuer_profile import IssuerProfile
from app.db.models.product import Product
from app.utils.dt import now_cr

NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

SCHEMAS_V44 = {
    "TE": {
        "root_tag": "TiqueteElectronico",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/tiqueteElectronico",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/tiqueteElectronico "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/tiqueteElectronico.xsd",
        "resumen_tag": "ResumenFactura",
    },
    "FE": {
        "root_tag": "FacturaElectronica",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica.xsd",
        "resumen_tag": "ResumenFactura",
    },
    "NC": {
        "root_tag": "NotaCreditoElectronica",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaCreditoElectronica",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaCreditoElectronica "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaCreditoElectronica.xsd",
        "resumen_tag": "ResumenFactura",
    },
    "ND": {
        "root_tag": "NotaDebitoElectronica",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaDebitoElectronica",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaDebitoElectronica "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaDebitoElectronica.xsd",
        "resumen_tag": "ResumenFactura",
    },
    "REP": {
        "root_tag": "ReciboElectronicoPago",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/reciboElectronicoPago",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/reciboElectronicoPago "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/reciboElectronicoPago.xsd",
        "resumen_tag": "ResumenReciboPago",
    },
    "FEC": {
        "root_tag": "FacturaElectronicaCompra",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaCompra",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaCompra "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaCompra.xsd",
        "resumen_tag": "ResumenFactura",
    },
    "FEE": {
        "root_tag": "FacturaElectronicaExportacion",
        "xmlns": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaExportacion",
        "schemaLocation": "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaExportacion "
                          "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaExportacion.xsd",
        "resumen_tag": "ResumenFactura",
    },
}

PAYMENT_MAP = {
    "efectivo": "01", "cash": "01",
    "tarjeta": "02", "card": "02",
    "cheque": "03",
    "transferencia": "04", "transfer": "04",
    "recaudado por terceros": "05", "terceros": "05",
    "sinpe": "06", "sinpe movil": "06",
    "plataforma digital": "07", "plataforma": "07",
}

# Códigos de impuesto que requieren nodo DatosImpuestoEspecifico
_IMPUESTOS_ESPECIFICOS = {"03", "04", "05", "06"}
# Códigos que usan tarifa porcentual (no DatosImpuestoEspecifico)
_IMPUESTOS_CON_TARIFA = {"01", "02", "07", "08", "12", "99"}


def _rfc3339_now() -> str:
    return now_cr().isoformat(timespec="seconds")

def _add(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    # Inherit namespace from parent so sub-elements validate against XSD
    ns = ""
    ptag = parent.tag
    if ptag.startswith("{"):
        ns = ptag.split("}")[0] + "}"
    el = ET.SubElement(parent, f"{ns}{tag}")
    if text is not None:
        el.text = str(text)
    return el

def _zfill(v: Any, n: int) -> str:
    return str(v).zfill(n)[-n:]

def _safe(v: Any, max_len: int) -> str:
    s = "" if v is None else str(v).strip()
    return s[:max_len]

def _require(obj: Any, attr: str, label: str):
    v = getattr(obj, attr, None)
    if v is None or str(v).strip() == "":
        raise ValueError(f"Falta dato obligatorio: {label} ({attr})")

def _payment_codes_from_sale(sale: Any) -> List[str]:
    raw = (getattr(sale, "payment_method", "") or "").strip().lower()
    if not raw:
        return ["01"]
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    codes = []
    for p in parts:
        codes.append(PAYMENT_MAP.get(p, "01"))
    out = []
    for c in codes:
        if c not in out:
            out.append(c)
    return out or ["01"]

def _round5(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

def _q(v: Decimal, places: str = "0.00001") -> Decimal:
    return v.quantize(Decimal(places), rounding=ROUND_HALF_UP)

def _q5(v: Decimal) -> Decimal:
    return _q(v, "0.00001")

def _assert_close(a: Decimal, b: Decimal, label: str, tol: Decimal = Decimal("0.02")) -> None:
    diff = (a - b).copy_abs()
    if diff > tol:
        raise ValueError(f"Inconsistencia {label}: {a} != {b} (diferencia: {diff})")

def _fmt_tarifa(rate_pct: Decimal) -> str:
    val = rate_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if val == val.to_integral_value():
        return str(int(val))
    return str(val).rstrip("0")

def _is_service(cabys_code: Optional[str]) -> bool:
    if not cabys_code or not cabys_code.strip():
        return False
    return cabys_code.strip()[0] in ("5", "6", "7", "8", "9")

def _is_merchandise(cabys_code: Optional[str]) -> bool:
    if not cabys_code or not cabys_code.strip():
        return True
    return cabys_code.strip()[0] in ("0", "1", "2", "3", "4")

def map_tax_rate_to_codigo_tarifa(tax_rate: float, tarifa_override: Optional[str] = None) -> tuple[str, str]:
    if tarifa_override and tax_rate == 0:
        if tarifa_override in ("01", "10", "11"):
            return tarifa_override, "0"
    if tax_rate >= 13:
        return "08", "13"
    elif tax_rate >= 4:
        return "04", "4"
    elif tax_rate >= 2:
        return "03", "2"
    elif tax_rate >= 1:
        return "02", "1"
    elif tax_rate >= 0.5:
        return "09", "0.5"
    else:
        return "10", "0"

def _has_receptor(customer: Any) -> bool:
    if not customer:
        return False
    return all(getattr(customer, a, None) for a in ("name", "id_number", "id_type"))

def _is_no_sujeto(codigo_tarifa: str) -> bool:
    return codigo_tarifa in ("01", "11")

def _getv(obj: Any, attr: str, default=None):
    """Safe getattr that also treats empty string as None."""
    v = getattr(obj, attr, default)
    if v is None:
        return default
    if isinstance(v, str) and not v.strip():
        return default
    return v


# ═════════════════════════════════════════════════════════════
# Acumuladores de resumen
# ═════════════════════════════════════════════════════════════

class _ResumenAccumulators:
    def __init__(self):
        self.serv_gravados = Decimal("0")
        self.serv_exentos = Decimal("0")
        self.serv_exonerados = Decimal("0")
        self.serv_no_sujetos = Decimal("0")

        self.merc_gravadas = Decimal("0")
        self.merc_exentas = Decimal("0")
        self.merc_exoneradas = Decimal("0")
        self.merc_no_sujetas = Decimal("0")

        self.total_descuentos = Decimal("0")
        self.total_impuesto = Decimal("0")
        self.total_imp_asum_emisor_fabrica = Decimal("0")

        # {(codigo_impuesto, codigo_tarifa_or_empty): monto_total}
        self.desglose: dict[tuple[str, str], Decimal] = {}
        self.desglose_asumidos: dict[tuple[str, str], bool] = {}

    def add_line(self, *, is_svc: bool, monto_total: Decimal, descuento: Decimal,
                 impuesto: Decimal, codigo_tarifa: str, rate_pct: Decimal,
                 imp_asumido_emisor: Decimal = Decimal("0"),
                 exon_monto: Decimal = Decimal("0"),
                 cod_impuesto: str = "01"):
        self.total_descuentos += descuento
        self.total_impuesto += impuesto
        self.total_imp_asum_emisor_fabrica += imp_asumido_emisor

        # Desglose: clave por (código impuesto, tarifa IVA si es IVA)
        tarifa_key = codigo_tarifa if cod_impuesto in ("01", "07") else ""
        key = (cod_impuesto, tarifa_key)

        if imp_asumido_emisor > 0:
            self.desglose_asumidos[key] = True
            self.desglose[key] = self.desglose.get(key, Decimal("0"))
        else:
            self.desglose[key] = self.desglose.get(key, Decimal("0")) + impuesto

        is_gravado = rate_pct > 0
        is_no_suj = _is_no_sujeto(codigo_tarifa)
        has_exon = exon_monto > 0

        if is_svc:
            if is_no_suj:
                self.serv_no_sujetos += monto_total
            elif has_exon:
                self.serv_exonerados += monto_total
            elif is_gravado:
                self.serv_gravados += monto_total
            else:
                self.serv_exentos += monto_total
        else:
            if is_no_suj:
                self.merc_no_sujetas += monto_total
            elif has_exon:
                self.merc_exoneradas += monto_total
            elif is_gravado:
                self.merc_gravadas += monto_total
            else:
                self.merc_exentas += monto_total

    def write_resumen(self, resumen: ET.Element, total_comprobante_out: list,
                      doc_type: str = "FE"):
        sg = _q5(self.serv_gravados)
        se = _q5(self.serv_exentos)
        seo = _q5(self.serv_exonerados)
        sns = _q5(self.serv_no_sujetos)
        mg = _q5(self.merc_gravadas)
        me = _q5(self.merc_exentas)
        meo = _q5(self.merc_exoneradas)
        mns = _q5(self.merc_no_sujetas)
        td = _q5(self.total_descuentos)
        ti = _q5(self.total_impuesto)
        ti_asum = _q5(self.total_imp_asum_emisor_fabrica)

        if sg > 0:
            _add(resumen, "TotalServGravados", str(sg))
        if se > 0:
            _add(resumen, "TotalServExentos", str(se))
        # FASE 3.4: TotalServExonerado
        if seo > 0 and doc_type not in ("FEE",):
            _add(resumen, "TotalServExonerado", str(seo))
        if sns > 0 and doc_type != "FEE":
            _add(resumen, "TotalServNoSujeto", str(sns))

        if mg > 0:
            _add(resumen, "TotalMercanciasGravadas", str(mg))
        if me > 0:
            _add(resumen, "TotalMercanciasExentas", str(me))
        # FASE 3.4: TotalMercExonerada
        if meo > 0 and doc_type not in ("FEE",):
            _add(resumen, "TotalMercExonerada", str(meo))
        if mns > 0 and doc_type != "FEE":
            _add(resumen, "TotalMercNoSujeta", str(mns))

        total_gravado = _q5(sg + mg)
        total_exento = _q5(se + me)
        total_exonerado = _q5(seo + meo) if doc_type != "FEE" else Decimal("0")
        total_no_sujeto = _q5(sns + mns) if doc_type != "FEE" else Decimal("0")

        if total_gravado > 0:
            _add(resumen, "TotalGravado", str(total_gravado))
        if total_exento > 0:
            _add(resumen, "TotalExento", str(total_exento))
        if total_exonerado > 0:
            _add(resumen, "TotalExonerado", str(total_exonerado))
        if total_no_sujeto > 0:
            _add(resumen, "TotalNoSujeto", str(total_no_sujeto))

        total_venta = _q5(total_gravado + total_exento + total_exonerado + total_no_sujeto)
        _add(resumen, "TotalVenta", str(total_venta))

        if td > 0:
            _add(resumen, "TotalDescuentos", str(td))

        total_venta_neta = _q5(total_venta - td)
        _add(resumen, "TotalVentaNeta", str(total_venta_neta))

        for (cod_imp, cod_tarifa), monto in self.desglose.items():
            nodo = _add(resumen, "TotalDesgloseImpuesto")
            _add(nodo, "Codigo", cod_imp)
            if cod_tarifa:
                _add(nodo, "CodigoTarifaIVA", cod_tarifa)
            _add(nodo, "TotalMontoImpuesto", str(_q5(monto)))

        if ti > 0:
            _add(resumen, "TotalImpuesto", str(ti))

        if ti_asum > 0 and doc_type not in ("FEE", "FEC"):
            _add(resumen, "TotalImpAsumEmisorFabrica", str(ti_asum))

        # TotalComprobante is NOT written here — the caller writes it
        # AFTER MedioPago, as required by the XSD element order.
        total_comprobante = _q5(total_venta_neta + ti)
        total_comprobante_out.append(total_comprobante)

        _assert_close(total_comprobante, (total_venta_neta + ti), "TotalComprobante")
        _assert_close(total_venta_neta, (total_venta - td), "TotalVentaNeta")


# ═════════════════════════════════════════════════════════════
# FASE 3: Procesador de línea de detalle con soporte completo v4.4
# ═════════════════════════════════════════════════════════════

def _prefetch_products(db: Session, details) -> dict:
    """FASE 3 — Fix 3.2: Prefetch todos los productos en UNA query."""
    product_ids = [d.product_id for d in details if getattr(d, "product_id", None)]
    if not product_ids:
        return {}
    products = db.query(Product).filter(Product.id.in_(set(product_ids))).all()
    return {p.id: p for p in products}


def _process_detail_line(
    db: Session, detalle: ET.Element, d: Any, line_num: int,
    doc_type: str, acc: _ResumenAccumulators,
    products_map: dict = None,
):
    # FASE 3 — Fix 3.2: Usar products_map prefetcheado para evitar N+1.
    # Si no se pasa el mapa, cae en query individual (retrocompatibilidad).
    if products_map and d.product_id in products_map:
        product = products_map[d.product_id]
    else:
        product = db.query(Product).filter(Product.id == d.product_id).first()
    if not product:
        raise ValueError(f"Producto no encontrado ID {d.product_id}")

    qty = Decimal(str(d.quantity))
    unit_gross = Decimal(str(d.unit_price))

    tax_rate_raw = Decimal(str(product.tax_rate or 0))
    if tax_rate_raw > 0 and tax_rate_raw < 1:
        rate_pct = tax_rate_raw * Decimal("100")
    else:
        rate_pct = tax_rate_raw

    rate_frac = rate_pct / Decimal("100")
    tax_factor = Decimal("1") + rate_frac
    unit_net = unit_gross / tax_factor if rate_frac > 0 else unit_gross

    monto_total = _q5(qty * unit_net)

    # ── Descuento ──
    descuento = Decimal("0")
    if d.discount_percent:
        descuento = _q5(monto_total * (Decimal(str(d.discount_percent)) / Decimal("100")))

    subtotal = _q5(monto_total - descuento)

    # ── Código de impuesto (FASE 3.5) ──
    cod_impuesto = _getv(d, "impuesto_code") or _getv(product, "impuesto_code") or "01"

    # ── IVA cobrado a fábrica (FASE 3.1) ──
    iva_fabrica = _getv(d, "iva_cobrado_fabrica") or _getv(product, "iva_cobrado_fabrica")

    # ── BaseImponible ──
    base_imponible = subtotal
    # Si hay impuestos específicos que se suman a la base (02, 04, 05, 12)
    # la base se ajustaría aquí. Por ahora solo base = subtotal.

    # ── Factor IVA Bienes Usados (código 08) ──
    factor_iva = _getv(d, "factor_calculo_iva") or _getv(product, "factor_calculo_iva")

    # ── Cálculo de impuesto ──
    impuesto = Decimal("0")
    tarifa_override = _getv(product, "tax_tarifa_code_override")

    if cod_impuesto == "08" and factor_iva:
        # IVA Bienes Usados: impuesto = factor × subtotal
        impuesto = _q5(Decimal(str(factor_iva)) * subtotal)
    elif cod_impuesto in ("01", "07") and rate_frac > 0:
        # IVA normal o IVA cálculo especial
        if iva_fabrica == "01":
            # Código 01 fábrica: emisor puede separar impuestos, base editable
            impuesto = _q5(base_imponible * rate_frac)
        else:
            impuesto = _q5(base_imponible * rate_frac)
    elif cod_impuesto == "02" and rate_frac > 0:
        # Selectivo de Consumo: tarifa × subtotal
        impuesto = _q5(subtotal * rate_frac)
    elif cod_impuesto == "12" and rate_frac > 0:
        # Cemento: 5% × subtotal
        impuesto = _q5(subtotal * Decimal("0.05"))
    elif cod_impuesto in _IMPUESTOS_ESPECIFICOS:
        # Impuestos específicos: se calculan con DatosImpuestoEspecifico
        imp_unidad = Decimal(str(_getv(product, "imp_esp_impuesto_unidad") or 0))
        cant_um = Decimal(str(_getv(product, "imp_esp_cantidad_unidad_medida") or 0))
        if cod_impuesto == "03":
            # Combustibles: CantidadUnidadMedida × ImpuestoUnidad
            impuesto = _q5(cant_um * imp_unidad)
        elif cod_impuesto == "04":
            # Bebidas Alcohólicas: Cantidad × Proporción × ImpuestoUnidad
            pct_alcohol = Decimal(str(_getv(product, "imp_esp_porcentaje") or 0))
            proporcion = _q5(cant_um * pct_alcohol / Decimal("100"))
            impuesto = _q5(qty * proporcion * imp_unidad)
        elif cod_impuesto == "05":
            # Bebidas sin alcohol: Cantidad × CantUM × (ImpUnidad / VolumenUC)
            vol_uc = Decimal(str(_getv(product, "imp_esp_volumen_unidad_consumo") or 1))
            if vol_uc > 0:
                impuesto = _q5(qty * cant_um * (imp_unidad / vol_uc))
        elif cod_impuesto == "06":
            # Tabaco: Cantidad × CantUM × ImpuestoUnidad
            impuesto = _q5(qty * cant_um * imp_unidad)
    elif cod_impuesto == "99" and rate_frac > 0:
        impuesto = _q5(subtotal * rate_frac)

    # ── Código de tarifa IVA ──
    if cod_impuesto in ("01", "07"):
        codigo_tarifa, tarifa_str = map_tax_rate_to_codigo_tarifa(float(rate_pct), tarifa_override)
    else:
        codigo_tarifa, tarifa_str = "", _fmt_tarifa(rate_pct)

    # ── Exoneración (FASE 3.4) ──
    exon_tipo = _getv(d, "exon_tipo_doc")
    exon_monto = Decimal("0")
    exon_tarifa_val = Decimal("0")
    if exon_tipo:
        exon_tarifa_val = Decimal(str(_getv(d, "exon_tarifa") or 0))
        # MontoExonerado = TarifaExonerada × Subtotal (o base imponible)
        exon_monto = _q5(exon_tarifa_val * subtotal / Decimal("100"))

    # ── Descuentos regalías/bonificaciones: IVA sobre MontoTotal ──
    disc_code = _getv(d, "discount_code") or _getv(product, "discount_code_default") or "07"
    is_regalia_o_bonif = disc_code in ("01", "03")
    if is_regalia_o_bonif and cod_impuesto == "01" and rate_frac > 0:
        # Regalías/Bonificaciones: IVA se calcula sobre MontoTotal (no subtotal)
        impuesto = _q5(monto_total * rate_frac)

    # ── ImpuestoAsumidoEmisorFabrica ──
    imp_asumido = Decimal("0")
    if is_regalia_o_bonif:
        # Regalías/bonificaciones: el impuesto es asumido por el emisor
        imp_asumido = impuesto
        if exon_monto > 0:
            imp_asumido = _q5(impuesto - exon_monto)
    if iva_fabrica:
        # IVA cobrado a fábrica: impuesto asumido
        imp_asumido = impuesto

    impuesto_neto = _q5(impuesto - exon_monto - imp_asumido)
    if impuesto_neto < 0:
        impuesto_neto = Decimal("0")
    monto_total_linea = _q5(subtotal + impuesto_neto)

    is_svc = _is_service(product.cabys_code)

    acc.add_line(
        is_svc=is_svc, monto_total=monto_total, descuento=descuento,
        impuesto=impuesto, codigo_tarifa=codigo_tarifa,
        rate_pct=rate_pct, imp_asumido_emisor=imp_asumido,
        exon_monto=exon_monto, cod_impuesto=cod_impuesto,
    )

    # ══════════════════════════════════════════════════
    # EMITIR XML de la línea
    # ══════════════════════════════════════════════════
    linea = _add(detalle, "LineaDetalle")
    _add(linea, "NumeroLinea", str(line_num))

    # PartidaArancelaria (FEE mercancías)
    if doc_type == "FEE" and _is_merchandise(product.cabys_code):
        pa = _getv(product, "partida_arancelaria")
        if pa:
            _add(linea, "PartidaArancelaria", _safe(pa, 12))
        else:
            raise ValueError(f"Producto '{product.name}' (ID {product.id}) requiere PartidaArancelaria para FEE.")

    # CodigoCABYS
    if product.cabys_code:
        _add(linea, "CodigoCABYS", _safe(product.cabys_code, 13))

    # FASE 1.1: RegistroFiscal8707
    reg_fiscal = _getv(product, "registro_fiscal_8707")
    if reg_fiscal:
        _add(linea, "Registrofiscal8707", _safe(reg_fiscal, 12))

    _add(linea, "Cantidad", f"{qty:.3f}".rstrip("0").rstrip("."))
    _add(linea, "UnidadMedida", product.unit_type or "Unid")

    # FASE 3.1: TipoTransaccion (nota 22)
    tipo_trans = _getv(d, "tipo_transaccion") or _getv(product, "tipo_transaccion")
    if tipo_trans and doc_type != "TE":
        _add(linea, "TipoTransaccion", _safe(tipo_trans, 2).zfill(2))

    _add(linea, "Detalle", _safe(product.name, 200))

    # FASE 3.1: NumeroVINoSerie (vehículos/aeronaves)
    vin = _getv(d, "numero_vin_serie") or _getv(product, "numero_vin_serie")
    if vin:
        _add(linea, "NumeroVINoSerie", _safe(vin, 17))

    # FASE 3.1: RegistroMedicamento
    reg_med = _getv(product, "registro_medicamento")
    if reg_med:
        _add(linea, "RegistroMedicamento", _safe(reg_med, 100))

    # FASE 3.1: FormaFarmaceutica (nota 19)
    forma_farm = _getv(product, "forma_farmaceutica")
    if forma_farm:
        _add(linea, "FormaFarmaceutica", _safe(forma_farm, 3))

    _add(linea, "PrecioUnitario", str(_round5(unit_net)))
    _add(linea, "MontoTotal", str(monto_total))

    # ── Descuento (FASE 3.3: dinámico) ──
    if descuento > 0:
        desc_node = _add(linea, "Descuento")
        _add(desc_node, "MontoDescuento", str(descuento))
        _add(desc_node, "CodigoDescuento", disc_code.zfill(2))
        if disc_code == "99":
            otro = _getv(d, "discount_code_otro") or ""
            if otro:
                _add(desc_node, "CodigoDescuentoOTRO", _safe(otro, 100))
            nat = _getv(d, "discount_description") or ""
            if nat:
                _add(desc_node, "NaturalezaDescuento", _safe(nat, 80))

    _add(linea, "SubTotal", str(subtotal))

    # FASE 3.1: IVACobradoFabrica (nota 21)
    if iva_fabrica and doc_type not in ("FEE", "FEC"):
        _add(linea, "IVACobradoFabrica", iva_fabrica)

    # BaseImponible (condición 4 en FEE)
    if doc_type != "FEE":
        _add(linea, "BaseImponible", str(base_imponible))

    # ── Impuesto ──
    imp_node = _add(linea, "Impuesto")
    _add(imp_node, "Codigo", cod_impuesto)

    # CodigoImpuestoOTRO (si código 99)
    if cod_impuesto == "99":
        imp_otro = _getv(d, "impuesto_code_otro") or _getv(product, "impuesto_code_otro")
        if imp_otro:
            _add(imp_node, "CodigoImpuestoOTRO", _safe(imp_otro, 100))

    # CodigoTarifaIVA (solo para IVA: 01, 07)
    if cod_impuesto in ("01", "07") and codigo_tarifa:
        _add(imp_node, "CodigoTarifaIVA", codigo_tarifa)

    # Tarifa (para impuestos con tarifa porcentual)
    if cod_impuesto in _IMPUESTOS_CON_TARIFA:
        if cod_impuesto == "12":
            _add(imp_node, "Tarifa", "5")
        else:
            _add(imp_node, "Tarifa", tarifa_str)

    # FASE 3.5: FactorCalculoIVA (código 08)
    if cod_impuesto == "08" and factor_iva:
        _add(imp_node, "FactorCalculoIVA", f"{float(factor_iva):.4f}")

    # FASE 3.5: DatosImpuestoEspecifico (códigos 03, 04, 05, 06)
    if cod_impuesto in _IMPUESTOS_ESPECIFICOS:
        datos_esp = _add(imp_node, "DatosImpuestoEspecifico")
        cant_um = Decimal(str(_getv(product, "imp_esp_cantidad_unidad_medida") or 0))
        _add(datos_esp, "CantidadUnidadMedida", f"{float(cant_um):.2f}")

        if cod_impuesto == "04":
            pct = Decimal(str(_getv(product, "imp_esp_porcentaje") or 0))
            _add(datos_esp, "Porcentaje", _fmt_tarifa(pct))
            proporcion = _q5(cant_um * pct / Decimal("100"))
            _add(datos_esp, "Proporcion", f"{float(proporcion):.2f}")

        if cod_impuesto == "05":
            vol = Decimal(str(_getv(product, "imp_esp_volumen_unidad_consumo") or 0))
            _add(datos_esp, "VolumenUnidadConsumo", f"{float(vol):.2f}")

        imp_unidad = Decimal(str(_getv(product, "imp_esp_impuesto_unidad") or 0))
        _add(datos_esp, "ImpuestoUnidad", str(_q5(imp_unidad)))

    _add(imp_node, "Monto", str(impuesto))

    # MontoExportacion (FEE mercancías)
    if doc_type == "FEE" and _is_merchandise(product.cabys_code):
        monto_exp = _getv(d, "monto_exportacion")
        if monto_exp and Decimal(str(monto_exp)) > 0:
            _add(imp_node, "MontoExportacion", str(_q5(Decimal(str(monto_exp)))))

    # ── Exoneración (FASE 3.4) ──
    if exon_tipo and doc_type not in ("FEE",):
        exon_node = _add(imp_node, "Exoneracion")
        _add(exon_node, "TipoDocumentoEX", exon_tipo.zfill(2))
        exon_tipo_otro = _getv(d, "exon_tipo_doc_otro")
        if exon_tipo == "99" and exon_tipo_otro:
            _add(exon_node, "TipoDocumentoOTRO", _safe(exon_tipo_otro, 100))
        _add(exon_node, "NumeroDocumento", _safe(_getv(d, "exon_numero_doc") or "", 40))

        exon_art = _getv(d, "exon_articulo")
        if exon_art and exon_tipo in ("02", "03", "06", "07", "08"):
            _add(exon_node, "Articulo", str(int(exon_art)))
            exon_inc = _getv(d, "exon_inciso")
            if exon_inc:
                _add(exon_node, "Inciso", str(int(exon_inc)))

        exon_inst = _getv(d, "exon_institucion") or "01"
        _add(exon_node, "NombreInstitucion", exon_inst.zfill(2))
        if exon_inst == "99":
            exon_inst_otro = _getv(d, "exon_institucion_otro") or ""
            if exon_inst_otro:
                _add(exon_node, "NombreInstitucionOtros", _safe(exon_inst_otro, 160))

        exon_fecha = _getv(d, "exon_fecha")
        if exon_fecha and hasattr(exon_fecha, "isoformat"):
            _add(exon_node, "FechaEmisionEX", exon_fecha.isoformat(timespec="seconds"))
        else:
            _add(exon_node, "FechaEmisionEX", _rfc3339_now())

        _add(exon_node, "TarifaExonerada", _fmt_tarifa(exon_tarifa_val))
        _add(exon_node, "MontoExoneracion", str(exon_monto))

    # ImpuestoAsumidoEmisorFabrica (condición 4 en FEE y FEC)
    if doc_type in ("FE", "TE", "NC", "ND"):
        _add(linea, "ImpuestoAsumidoEmisorFabrica", str(imp_asumido))

    _add(linea, "ImpuestoNeto", str(impuesto_neto))
    _add(linea, "MontoTotalLinea", str(monto_total_linea))


def _write_medio_pago(resumen: ET.Element, sale: Any, total_comprobante: Decimal):
    payment_codes = _payment_codes_from_sale(sale)
    if len(payment_codes) == 1:
        mp_node = _add(resumen, "MedioPago")
        _add(mp_node, "TipoMedioPago", payment_codes[0])
    else:
        payment_amounts = getattr(sale, "payment_amounts", None)
        if payment_amounts and isinstance(payment_amounts, dict):
            for code in payment_codes:
                mp_node = _add(resumen, "MedioPago")
                _add(mp_node, "TipoMedioPago", code)
                amt = Decimal("0")
                for raw_name, raw_amt in payment_amounts.items():
                    mapped = PAYMENT_MAP.get(raw_name.strip().lower(), "01")
                    if mapped == code:
                        amt += Decimal(str(raw_amt))
                _add(mp_node, "TotalMedioPago", str(_q5(amt)))
        else:
            mp_node = _add(resumen, "MedioPago")
            _add(mp_node, "TipoMedioPago", payment_codes[0])


# ═════════════════════════════════════════════════════════════
# FASE 5.3: Helper para moneda multi-divisa
# ═════════════════════════════════════════════════════════════

def _write_moneda(resumen: ET.Element, sale_or_payment: Any, default_moneda: str = "CRC"):
    """
    Escribe CodigoTipoMoneda leyendo del objeto sale/payment.
    Soporta Sale.moneda_code y Sale.tipo_cambio.
    PDF v4.4: CRC → TipoCambio="1", USD → tipo cambio de venta BCCR,
              otras monedas → tipo cambio respecto a colones.
    """
    moneda_code = _getv(sale_or_payment, "moneda_code") or default_moneda
    tipo_cambio = _getv(sale_or_payment, "tipo_cambio") or ("1" if moneda_code == "CRC" else "1.00")

    mon = _add(resumen, "CodigoTipoMoneda")
    _add(mon, "CodigoMoneda", _safe(moneda_code, 3))
    _add(mon, "TipoCambio", str(tipo_cambio))


# ═════════════════════════════════════════════════════════════
# FASE 5.5: Helper para InformacionReferencia en FE
# ═════════════════════════════════════════════════════════════

def _check_exon_code_11(sale_details_objs: List[Any]) -> bool:
    """
    Revisa si alguna línea de detalle usa exon_tipo_doc == '11'
    (Autorización de Impuesto Local Concreta). En ese caso,
    InformacionReferencia es obligatoria en FE (v4.4 change #125).
    """
    for d in sale_details_objs:
        exon_tipo = _getv(d, "exon_tipo_doc")
        if exon_tipo and exon_tipo.strip() == "11":
            return True
    return False


def _write_info_referencia(root: ET.Element, referencia_doc: Any,
                           codigo_referencia: str = "04",
                           razon_referencia: str = "Referencia"):
    """
    FASE 5.5+5.6: Escribe nodo InformacionReferencia con soporte completo.
    Soporta todos los códigos nota 9 v4.4 (01-12, 99) y TipoDocRefOTRO para 99.
    """
    ir = _add(root, "InformacionReferencia")
    tipo_doc_ref = _safe(getattr(referencia_doc, "tipo_doc", "99"), 2).zfill(2)
    _add(ir, "TipoDocIR", tipo_doc_ref)
    if tipo_doc_ref == "99":
        ref_otro = _getv(referencia_doc, "tipo_doc_otro")
        if ref_otro:
            _add(ir, "TipoDocRefOTRO", _safe(ref_otro, 100))
    numero_ref = _getv(referencia_doc, "numero") or _getv(referencia_doc, "clave") or ""
    _add(ir, "Numero", _safe(numero_ref, 50))
    fecha_ref = _getv(referencia_doc, "fecha")
    if fecha_ref and hasattr(fecha_ref, "isoformat"):
        if hasattr(fecha_ref, "hour"):
            _add(ir, "FechaEmisionIR", fecha_ref.isoformat(timespec="seconds"))
        else:
            _add(ir, "FechaEmisionIR", fecha_ref.isoformat() + "T00:00:00-06:00")
    else:
        _add(ir, "FechaEmisionIR", _rfc3339_now())
    cod_ref = _safe(codigo_referencia, 2).zfill(2)
    _add(ir, "Codigo", cod_ref)
    if cod_ref == "99":
        cod_ref_otro = _getv(referencia_doc, "codigo_referencia_otro")
        if cod_ref_otro:
            _add(ir, "CodigoReferenciaOTRO", _safe(cod_ref_otro, 100))
    _add(ir, "Razon", _safe(razon_referencia, 180))


# ═════════════════════════════════════════════════════════════
# FASE 3.2: Helper para CondicionVenta con soporte completo
# ═════════════════════════════════════════════════════════════

def _write_condicion_venta(root: ET.Element, sale: Any, doc_type: str):
    """
    Emite CondicionVenta con soporte para códigos 01-15 y 99.
    FASE 3.2: Soporta CondicionVentaOtros para código 99,
    y nuevos códigos 12-15 de v4.4.
    """
    forced = (getattr(sale, "condicion_venta_code", None) or "").strip()

    if forced:
        if not forced.isdigit() or len(forced) > 2:
            raise ValueError("condicion_venta_code inválido (debe ser '01','02','10','99', etc.)")
        cond = forced.zfill(2)
    else:
        raw_pm = (getattr(sale, "payment_method", "") or "").strip().lower()
        CONDICION_VENTA = {
            "efectivo": "01", "tarjeta": "01", "transferencia": "01",
            "sinpe": "01", "sinpe movil": "01", "credito": "02", "crédito": "02",
        }
        cond = CONDICION_VENTA.get(raw_pm, "01")

    _add(root, "CondicionVenta", cond)

    # FASE 3.2: CondicionVentaOtros obligatorio si código 99
    if cond == "99":
        otros = _getv(sale, "condicion_venta_otros") or ""
        if not otros:
            raise ValueError("CondicionVentaOtros es obligatorio cuando CondicionVenta = 99.")
        _add(root, "CondicionVentaOtros", _safe(otros, 100))

    # PlazoCredito obligatorio para 02 y 10
    if cond in ("02", "10"):
        plazo = getattr(sale, "credit_days", None)
        if not plazo or int(plazo) <= 0:
            raise ValueError("PlazoCredito es obligatorio y debe ser > 0 cuando CondicionVenta es 02 o 10.")
        _add(root, "PlazoCredito", str(int(plazo)))

    return cond


# ═════════════════════════════════════════════════════════════
# FASE 4: Helpers para emisor y receptor con campos completos
# ═════════════════════════════════════════════════════════════

def _write_emisor_std(root: ET.Element, issuer: Any) -> ET.Element:
    """
    Escribe el nodo Emisor estándar (usado en FE, TE, NC, ND, FEE).
    FASE 4.4: Incluye Teléfono del emisor cuando existe.
    Retorna el nodo emisor por si se necesita agregar más hijos.
    """
    emisor = _add(root, "Emisor")
    _add(emisor, "Nombre", _safe(issuer.legal_name, 100))
    eid = _add(emisor, "Identificacion")
    _add(eid, "Tipo", _safe(issuer.id_type, 2))
    _add(eid, "Numero", _safe(issuer.id_number, 20))
    if issuer.commercial_name:
        _add(emisor, "NombreComercial", _safe(issuer.commercial_name, 80))
    ubi = _add(emisor, "Ubicacion")
    _add(ubi, "Provincia", _zfill(issuer.provincia, 1))
    _add(ubi, "Canton", _zfill(issuer.canton, 2))
    _add(ubi, "Distrito", _zfill(issuer.distrito, 2))
    _add(ubi, "Barrio", _zfill(issuer.barrio, 5))
    _add(ubi, "OtrasSenas", _safe(issuer.otras_senas, 250))
    # FASE 4.4: Teléfono del emisor (opcional)
    iss_phone = _getv(issuer, "phone")
    if iss_phone:
        tel = _add(emisor, "Telefono")
        _add(tel, "CodigoPais", _safe(_getv(issuer, "phone_country_code") or "506", 3))
        _add(tel, "NumTelefono", _safe(iss_phone, 20))
    if issuer.email:
        _add(emisor, "CorreoElectronico", _safe(issuer.email, 160))
    return emisor


def _write_receptor(root: ET.Element, customer: Any, doc_type: str) -> Optional[ET.Element]:
    """
    Escribe el nodo Receptor completo con todos los campos v4.4.
    FASE 4.1: Ubicación del receptor (condicional).
    FASE 4.2: OtrasSenasExtranjero (tipo 05).
    FASE 4.3: NombreComercial (opcional).
    FASE 4.4: Teléfono del receptor (opcional).

    Reglas de condicionalidad por doc_type (PDF v4.4):
    - FE: Receptor obligatorio. Ubicación condición 2 (si tiene domicilio).
    - TE: Receptor condición 2. Ubicación condición 3 (opcional).
    - NC/ND: Receptor condición 2. Ubicación condición 2.
    - FEE: Receptor obligatorio. Ubicación condición 4 (NO aplica para Extranjero).
    - REP: Receptor obligatorio. Ubicación condición 2.

    No aplica Ubicación para tipo identificación 05 (Extranjero No Domiciliado).
    Retorna el nodo receptor o None si no se escribió.
    """
    if not _has_receptor(customer):
        return None

    receptor = _add(root, "Receptor")
    _add(receptor, "Nombre", _safe(customer.name, 100))

    rid = _add(receptor, "Identificacion")
    _add(rid, "Tipo", _safe(customer.id_type, 2))
    _add(rid, "Numero", _safe(customer.id_number, 20))

    # FASE 4.3: NombreComercial del receptor (opcional)
    cust_commercial = _getv(customer, "commercial_name")
    if cust_commercial:
        _add(receptor, "NombreComercial", _safe(cust_commercial, 80))

    # FASE 4.1: Ubicación del receptor
    # No aplica para Extranjero No Domiciliado (tipo 05)
    cust_id_type = _safe(customer.id_type, 2)
    is_extranjero = cust_id_type == "05"

    if not is_extranjero:
        # Verificar si tiene datos de ubicación
        prov = _getv(customer, "province_id")
        cant = _getv(customer, "canton_id")
        dist = _getv(customer, "district_id")

        if prov and cant and dist:
            rubi = _add(receptor, "Ubicacion")
            _add(rubi, "Provincia", _zfill(prov, 1))
            _add(rubi, "Canton", _zfill(cant, 2))
            _add(rubi, "Distrito", _zfill(dist, 2))
            # Barrio: mapear neighborhood
            barrio = _getv(customer, "neighborhood")
            if barrio:
                _add(rubi, "Barrio", _zfill(barrio, 5))
            # OtrasSenas: usar campo específico o fallback a address
            otras = _getv(customer, "otras_senas") or _getv(customer, "address")
            if otras:
                _add(rubi, "OtrasSenas", _safe(otras, 160))

    # FASE 4.2: OtrasSenasExtranjero (tipo 05)
    if is_extranjero or doc_type == "FEE":
        cust_senas_ext = _getv(customer, "otras_senas_extranjero")
        if cust_senas_ext:
            _add(receptor, "OtrasSenasExtranjero", _safe(cust_senas_ext, 300))

    # FASE 4.4: Teléfono del receptor (opcional)
    cust_phone = _getv(customer, "phone")
    if cust_phone:
        tel = _add(receptor, "Telefono")
        _add(tel, "CodigoPais", _safe(_getv(customer, "phone_country_code") or "506", 3))
        _add(tel, "NumTelefono", _safe(cust_phone, 20))

    if _getv(customer, "email"):
        _add(receptor, "CorreoElectronico", _safe(customer.email, 160))

    return receptor


# ═════════════════════════════════════════════════════════════
# Builder principal: FE y TE
# ═════════════════════════════════════════════════════════════

def build_xml_for_sale_v44(
    db: Session, *, sale: Any, sale_details: List[Any],
    clave: str, consecutivo: str, customer: Optional[Any] = None,
    referencia_doc: Optional[Any] = None,
    codigo_referencia: str = "04",
    razon_referencia: str = "Referencia",
) -> str:
    """
    Builder FE/TE.
    FASE 5.3: Soporta multi-moneda via sale.moneda_code / sale.tipo_cambio.
    FASE 5.5: Acepta referencia_doc opcional. Se auto-requiere si exon código 11.
    FASE 5.6: Soporta todos los códigos de referencia nota 9 (01-12, 99).
    """
    doc_type = "TE" if getattr(sale, "document_type", "04") == "04" else "FE"
    schema = SCHEMAS_V44[doc_type]

    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile. Configura el emisor en /settings/issuer-profile")
    _require(issuer, "provider_system_id", "ProveedorSistemas")
    _require(issuer, "economic_activity_code", "CodigoActividadEmisor")
    for f in ("provincia", "canton", "distrito", "barrio", "otras_senas"):
        _require(issuer, f, f"Emisor.{f}")

    ET.register_namespace("", schema["xmlns"])
    ET.register_namespace("xsi", NS_XSI)
    root = ET.Element(f"{{{schema["xmlns"]}}}{schema["root_tag"]}", {f"{{{NS_XSI}}}schemaLocation": schema["schemaLocation"]})

    _add(root, "Clave", clave)
    _add(root, "ProveedorSistemas", _safe(issuer.provider_system_id, 20))
    _add(root, "CodigoActividadEmisor", _zfill(issuer.economic_activity_code, 6))
    if _has_receptor(customer):
        car = _getv(customer, "economic_activity_code")
        if car:
            _add(root, "CodigoActividadReceptor", _zfill(car, 6))
    _add(root, "NumeroConsecutivo", consecutivo)
    _add(root, "FechaEmision", _rfc3339_now())

    _write_emisor_std(root, issuer)

    if doc_type != "TE":
        if not _has_receptor(customer):
            raise ValueError("FE requiere un receptor con nombre, id_type e id_number.")
        _write_receptor(root, customer, doc_type)
    else:
        _write_receptor(root, customer, doc_type)  # returns None if no customer

    _write_condicion_venta(root, sale, doc_type)

    detalle = _add(root, "DetalleServicio")
    acc = _ResumenAccumulators()
    _pmap = _prefetch_products(db, sale_details)
    for i, d in enumerate(sale_details, start=1):
        _process_detail_line(db, detalle, d, i, doc_type, acc, products_map=_pmap)

    resumen = _add(root, schema["resumen_tag"])
    _write_moneda(resumen, sale)
    total_comprobante_out: list[Decimal] = []
    acc.write_resumen(resumen, total_comprobante_out, doc_type=doc_type)
    total_comprobante = total_comprobante_out[0]
    _write_medio_pago(resumen, sale, total_comprobante)
    _add(resumen, "TotalComprobante", str(total_comprobante))

    # FASE 5.5: InformacionReferencia en FE
    # Obligatoria cuando exon código 11 (nota 10.1 v4.4 change #125).
    # También se emite si el caller pasa referencia_doc explícitamente.
    if referencia_doc:
        _write_info_referencia(root, referencia_doc, codigo_referencia, razon_referencia)
    elif doc_type == "FE" and _check_exon_code_11(sale_details):
        # Exon 11 detected pero no se pasó referencia — advertencia
        raise ValueError(
            "InformacionReferencia es obligatoria en FE cuando se usa "
            "exoneración código 11 (Autorización Local Concreta). "
            "Pase referencia_doc al builder."
        )

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


# ═════════════════════════════════════════════════════════════
# Builder REP
# ═════════════════════════════════════════════════════════════

def build_xml_for_rep_v44(
    db: Session, *, payment: Any, customer: Any,
    referenced_einvoices: List[Any], clave: str, consecutivo: str,
    condicion_venta_rep: str = "11", codigo_referencia: str = "01",
    razon_referencia: str = "Pago registrado",
) -> str:
    if condicion_venta_rep not in ("09", "11"):
        raise ValueError("En REP, CondicionVenta solo permite 09 o 11 (v4.4).")
    if not referenced_einvoices:
        raise ValueError("REP requiere al menos 1 referencia.")

    schema = SCHEMAS_V44["REP"]
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")
    _require(issuer, "provider_system_id", "ProveedorSistemas")
    _require(issuer, "economic_activity_code", "CodigoActividadEmisor")
    for f in ("provincia", "canton", "distrito", "barrio", "otras_senas"):
        _require(issuer, f, f"Emisor.{f}")
    if not _has_receptor(customer):
        raise ValueError("REP requiere un receptor.")

    ET.register_namespace("", schema["xmlns"])
    ET.register_namespace("xsi", NS_XSI)
    root = ET.Element(f"{{{schema["xmlns"]}}}{schema["root_tag"]}", {f"{{{NS_XSI}}}schemaLocation": schema["schemaLocation"]})

    _add(root, "Clave", clave)
    _add(root, "ProveedorSistemas", _safe(issuer.provider_system_id, 20))
    _add(root, "CodigoActividadEmisor", _zfill(issuer.economic_activity_code, 6))
    _add(root, "NumeroConsecutivo", consecutivo)
    _add(root, "FechaEmision", _rfc3339_now())

    _write_emisor_std(root, issuer)
    _write_receptor(root, customer, "REP")

    _add(root, "CondicionVenta", condicion_venta_rep)

    ALLOWED = {"01", "02", "03", "04", "07", "08", "10"}
    for einv in referenced_einvoices:
        tipo_doc_ir = (getattr(einv, "document_type", None) or "").zfill(2)
        if tipo_doc_ir not in ALLOWED:
            raise ValueError(f"TipoDocIR {tipo_doc_ir} no permitido en REP.")
        numero_ref = getattr(einv, "clave", None) or getattr(einv, "consecutivo", None)
        if not numero_ref:
            raise ValueError("Referencia sin clave/consecutivo.")
        sale_ref = getattr(einv, "sale", None)
        if not sale_ref or not getattr(sale_ref, "created_at", None):
            raise ValueError("Referencia sin sale.created_at.")
        ir = _add(root, "InformacionReferencia")
        _add(ir, "TipoDocIR", tipo_doc_ir)
        _add(ir, "Numero", _safe(numero_ref, 50))
        _add(ir, "FechaEmisionIR", sale_ref.created_at.astimezone().isoformat(timespec="seconds"))
        _add(ir, "Codigo", _safe(codigo_referencia, 2))
        _add(ir, "Razon", _safe(razon_referencia, 180))

    detalle = _add(root, "DetalleServicio")
    amt = Decimal(str(getattr(payment, "amount", 0) or 0)).quantize(Decimal("0.00001"))
    linea = _add(detalle, "LineaDetalle")
    _add(linea, "NumeroLinea", "1")
    _add(linea, "Cantidad", "1.000")
    _add(linea, "UnidadMedida", "Unid")
    _add(linea, "Detalle", "Pago / Abono")
    _add(linea, "PrecioUnitario", str(amt))
    _add(linea, "MontoTotal", str(amt))
    _add(linea, "SubTotal", str(amt))
    imp = _add(linea, "Impuesto")
    _add(imp, "Codigo", "01")
    _add(imp, "CodigoTarifaIVA", "10")
    _add(imp, "Tarifa", "0")
    _add(imp, "Monto", "0")
    _add(linea, "ImpuestoNeto", "0")
    _add(linea, "MontoTotalLinea", str(amt))

    resumen = _add(root, schema["resumen_tag"])
    moneda = _add(resumen, "CodigoTipoMoneda")
    _add(moneda, "CodigoMoneda", "CRC")
    _add(moneda, "TipoCambio", "1.00")
    _add(resumen, "TotalExento", str(amt))
    _add(resumen, "TotalVenta", str(amt))
    _add(resumen, "TotalVentaNeta", str(amt))
    nodo_desglose = _add(resumen, "TotalDesgloseImpuesto")
    _add(nodo_desglose, "Codigo", "01")
    _add(nodo_desglose, "CodigoTarifaIVA", "10")
    _add(nodo_desglose, "TotalMontoImpuesto", "0")
    pm_raw = (getattr(payment, "payment_method", "") or "").strip().lower()
    tipo_medio = PAYMENT_MAP.get(pm_raw, "01")
    mp_node = _add(resumen, "MedioPago")
    _add(mp_node, "TipoMedioPago", tipo_medio)
    _add(resumen, "TotalComprobante", str(amt))

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


# ═════════════════════════════════════════════════════════════
# NC builder
# ═════════════════════════════════════════════════════════════
def build_xml_for_nc_v44(
    db: Session, *, sale: Any, sale_details: List[Any], clave: str,
    consecutivo: str, customer: Optional[Any] = None,
    original_einv: Any, razon: str = "Anulación de comprobante",
) -> str:
    schema = SCHEMAS_V44["NC"]
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")
    _require(issuer, "provider_system_id", "ProveedorSistemas")
    _require(issuer, "economic_activity_code", "CodigoActividadEmisor")
    for f in ("provincia", "canton", "distrito", "barrio", "otras_senas"):
        _require(issuer, f, f"Emisor.{f}")

    ET.register_namespace("", schema["xmlns"])
    ET.register_namespace("xsi", NS_XSI)
    root = ET.Element(f"{{{schema["xmlns"]}}}{schema["root_tag"]}", {f"{{{NS_XSI}}}schemaLocation": schema["schemaLocation"]})

    _add(root, "Clave", clave)
    _add(root, "ProveedorSistemas", _safe(issuer.provider_system_id, 20))
    _add(root, "CodigoActividadEmisor", _zfill(issuer.economic_activity_code, 6))
    _add(root, "NumeroConsecutivo", consecutivo)
    _add(root, "FechaEmision", _rfc3339_now())

    _write_emisor_std(root, issuer)
    _write_receptor(root, customer, "NC")

    _add(root, "CondicionVenta", "01")

    detalle = _add(root, "DetalleServicio")
    acc = _ResumenAccumulators()
    _pmap = _prefetch_products(db, sale_details)
    for i, d in enumerate(sale_details, start=1):
        _process_detail_line(db, detalle, d, i, "NC", acc, products_map=_pmap)

    resumen = _add(root, schema["resumen_tag"])
    _write_moneda(resumen, sale)
    total_comprobante_out: list[Decimal] = []
    acc.write_resumen(resumen, total_comprobante_out, doc_type="NC")
    total_comprobante = total_comprobante_out[0]
    _write_medio_pago(resumen, sale, total_comprobante)
    _add(resumen, "TotalComprobante", str(total_comprobante))

    tipo_doc_original = (getattr(original_einv, "document_type", None) or "").zfill(2)
    numero_ref = getattr(original_einv, "clave", None) or getattr(original_einv, "consecutivo", None)
    if not numero_ref:
        raise ValueError("Documento original sin clave/consecutivo.")
    sale_original = getattr(original_einv, "sale", None)
    if not sale_original or not getattr(sale_original, "created_at", None):
        raise ValueError("Referencia sin sale.created_at.")

    ir = _add(root, "InformacionReferencia")
    _add(ir, "TipoDocIR", tipo_doc_original)
    _add(ir, "Numero", _safe(numero_ref, 50))
    _add(ir, "FechaEmisionIR", sale_original.created_at.astimezone().isoformat(timespec="seconds"))
    _add(ir, "Codigo", "01")
    _add(ir, "Razon", _safe(razon, 180))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ═════════════════════════════════════════════════════════════
# ND builder
# ═════════════════════════════════════════════════════════════
def build_xml_for_nd_v44(
    db: Session, *, sale: Any, sale_details: List[Any], clave: str,
    consecutivo: str, customer: Optional[Any] = None,
    original_einv: Any, razon: str = "Corrección de monto",
    codigo_referencia: str = "02",
) -> str:
    schema = SCHEMAS_V44["ND"]
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")
    _require(issuer, "provider_system_id", "ProveedorSistemas")
    _require(issuer, "economic_activity_code", "CodigoActividadEmisor")
    for f in ("provincia", "canton", "distrito", "barrio", "otras_senas"):
        _require(issuer, f, f"Emisor.{f}")

    ET.register_namespace("", schema["xmlns"])
    ET.register_namespace("xsi", NS_XSI)
    root = ET.Element(f"{{{schema["xmlns"]}}}{schema["root_tag"]}", {f"{{{NS_XSI}}}schemaLocation": schema["schemaLocation"]})

    _add(root, "Clave", clave)
    _add(root, "ProveedorSistemas", _safe(issuer.provider_system_id, 20))
    _add(root, "CodigoActividadEmisor", _zfill(issuer.economic_activity_code, 6))
    _add(root, "NumeroConsecutivo", consecutivo)
    _add(root, "FechaEmision", _rfc3339_now())

    _write_emisor_std(root, issuer)
    _write_receptor(root, customer, "ND")

    _add(root, "CondicionVenta", "01")

    detalle = _add(root, "DetalleServicio")
    acc = _ResumenAccumulators()
    _pmap = _prefetch_products(db, sale_details)
    for i, d in enumerate(sale_details, start=1):
        _process_detail_line(db, detalle, d, i, "ND", acc, products_map=_pmap)

    resumen = _add(root, schema["resumen_tag"])
    _write_moneda(resumen, sale)
    total_comprobante_out: list[Decimal] = []
    acc.write_resumen(resumen, total_comprobante_out, doc_type="ND")
    total_comprobante = total_comprobante_out[0]
    _write_medio_pago(resumen, sale, total_comprobante)
    _add(resumen, "TotalComprobante", str(total_comprobante))

    tipo_doc_original = (getattr(original_einv, "document_type", None) or "").zfill(2)
    numero_ref = getattr(original_einv, "clave", None) or getattr(original_einv, "consecutivo", None)
    if not numero_ref:
        raise ValueError("Documento original sin clave/consecutivo.")
    sale_original = getattr(original_einv, "sale", None)
    if not sale_original or not getattr(sale_original, "created_at", None):
        raise ValueError("Referencia sin sale.created_at.")

    ir = _add(root, "InformacionReferencia")
    _add(ir, "TipoDocIR", tipo_doc_original)
    _add(ir, "Numero", _safe(numero_ref, 50))
    _add(ir, "FechaEmisionIR", sale_original.created_at.astimezone().isoformat(timespec="seconds"))
    _add(ir, "Codigo", codigo_referencia)
    _add(ir, "Razon", _safe(razon, 180))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ═════════════════════════════════════════════════════════════
# FEC builder (Fase 2.1 — sin cambios de Fase 3)
# ═════════════════════════════════════════════════════════════
def build_xml_for_fec_v44(
    db: Session, *, purchase: Any, purchase_details: List[Any],
    supplier: Any, clave: str, consecutivo: str,
    condicion_venta: str = "01", referencia_doc: Optional[Any] = None,
    razon_referencia: str = "Compra a proveedor", codigo_referencia: str = "04",
) -> str:
    schema = SCHEMAS_V44["FEC"]
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")
    _require(issuer, "provider_system_id", "ProveedorSistemas")
    _require(issuer, "economic_activity_code", "CodigoActividadEmisor")
    for f in ("provincia", "canton", "distrito", "barrio", "otras_senas"):
        _require(issuer, f, f"Emisor.{f}")
    _require(supplier, "name", "Proveedor.nombre")
    _require(supplier, "id_type", "Proveedor.id_type")
    _require(supplier, "id_number", "Proveedor.id_number")

    supplier_id_type = _safe(supplier.id_type, 2)
    needs_ubicacion = supplier_id_type not in ("05", "06")
    if needs_ubicacion:
        for f in ("provincia", "canton", "distrito", "otras_senas"):
            _require(supplier, f, f"Proveedor.{f}")

    ET.register_namespace("", schema["xmlns"])
    ET.register_namespace("xsi", NS_XSI)
    root = ET.Element(f"{{{schema["xmlns"]}}}{schema["root_tag"]}", {f"{{{NS_XSI}}}schemaLocation": schema["schemaLocation"]})

    _add(root, "Clave", clave)
    _add(root, "ProveedorSistemas", _safe(issuer.provider_system_id, 20))
    sup_act = _getv(supplier, "economic_activity_code")
    if sup_act:
        _add(root, "CodigoActividadEmisor", _zfill(sup_act, 6))
    _add(root, "CodigoActividadReceptor", _zfill(issuer.economic_activity_code, 6))
    _add(root, "NumeroConsecutivo", consecutivo)
    _add(root, "FechaEmision", _rfc3339_now())

    emisor = _add(root, "Emisor")
    _add(emisor, "Nombre", _safe(supplier.name, 100))
    eid = _add(emisor, "Identificacion")
    _add(eid, "Tipo", supplier_id_type)
    _add(eid, "Numero", _safe(supplier.id_number, 20))
    sup_commercial = _getv(supplier, "commercial_name")
    if sup_commercial:
        _add(emisor, "NombreComercial", _safe(sup_commercial, 80))
    if needs_ubicacion:
        ubi = _add(emisor, "Ubicacion")
        _add(ubi, "Provincia", _zfill(supplier.provincia, 1))
        _add(ubi, "Canton", _zfill(supplier.canton, 2))
        _add(ubi, "Distrito", _zfill(supplier.distrito, 2))
        sup_barrio = _getv(supplier, "barrio")
        if sup_barrio:
            _add(ubi, "Barrio", _zfill(sup_barrio, 5))
        _add(ubi, "OtrasSenas", _safe(supplier.otras_senas, 250))
    elif supplier_id_type == "06":
        has_ubi = all(_getv(supplier, f) for f in ("provincia", "canton", "distrito", "otras_senas"))
        if has_ubi:
            ubi = _add(emisor, "Ubicacion")
            _add(ubi, "Provincia", _zfill(supplier.provincia, 1))
            _add(ubi, "Canton", _zfill(supplier.canton, 2))
            _add(ubi, "Distrito", _zfill(supplier.distrito, 2))
            sup_barrio = _getv(supplier, "barrio")
            if sup_barrio:
                _add(ubi, "Barrio", _zfill(sup_barrio, 5))
            _add(ubi, "OtrasSenas", _safe(supplier.otras_senas, 250))
    if supplier_id_type == "05":
        sup_senas_ext = _getv(supplier, "otras_senas_extranjero")
        if sup_senas_ext:
            _add(emisor, "OtrasSenasExtranjero", _safe(sup_senas_ext, 300))
    sup_phone = _getv(supplier, "phone")
    if sup_phone:
        tel = _add(emisor, "Telefono")
        _add(tel, "CodigoPais", _safe(_getv(supplier, "phone_country_code") or "506", 3))
        _add(tel, "NumTelefono", _safe(sup_phone, 20))
    sup_email = _getv(supplier, "email")
    if sup_email:
        _add(emisor, "CorreoElectronico", _safe(sup_email, 160))

    receptor = _add(root, "Receptor")
    _add(receptor, "Nombre", _safe(issuer.legal_name, 100))
    rid = _add(receptor, "Identificacion")
    _add(rid, "Tipo", _safe(issuer.id_type, 2))
    _add(rid, "Numero", _safe(issuer.id_number, 20))
    if issuer.commercial_name:
        _add(receptor, "NombreComercial", _safe(issuer.commercial_name, 80))
    rubi = _add(receptor, "Ubicacion")
    _add(rubi, "Provincia", _zfill(issuer.provincia, 1))
    _add(rubi, "Canton", _zfill(issuer.canton, 2))
    _add(rubi, "Distrito", _zfill(issuer.distrito, 2))
    _add(rubi, "Barrio", _zfill(issuer.barrio, 5))
    _add(rubi, "OtrasSenas", _safe(issuer.otras_senas, 250))
    # FASE 4.4: Teléfono del receptor (nuestra empresa en FEC)
    iss_phone = _getv(issuer, "phone")
    if iss_phone:
        tel = _add(receptor, "Telefono")
        _add(tel, "CodigoPais", _safe(_getv(issuer, "phone_country_code") or "506", 3))
        _add(tel, "NumTelefono", _safe(iss_phone, 20))
    if issuer.email:
        _add(receptor, "CorreoElectronico", _safe(issuer.email, 160))

    _add(root, "CondicionVenta", condicion_venta.zfill(2))
    if condicion_venta in ("02", "10"):
        plazo = _getv(purchase, "credit_days")
        if plazo and int(plazo) > 0:
            _add(root, "PlazoCredito", str(int(plazo)))

    detalle = _add(root, "DetalleServicio")
    acc = _ResumenAccumulators()
    _pmap = _prefetch_products(db, purchase_details)
    for i, d in enumerate(purchase_details, start=1):
        _process_detail_line(db, detalle, d, i, "FEC", acc, products_map=_pmap)

    resumen = _add(root, schema["resumen_tag"])
    _write_moneda(resumen, purchase)
    total_comprobante_out: list[Decimal] = []
    acc.write_resumen(resumen, total_comprobante_out, doc_type="FEC")
    total_comprobante = total_comprobante_out[0]
    _write_medio_pago(resumen, purchase, total_comprobante)
    _add(resumen, "TotalComprobante", str(total_comprobante))

    if referencia_doc:
        ir = _add(root, "InformacionReferencia")
        tipo_doc_ref = _safe(getattr(referencia_doc, "tipo_doc", "99"), 2).zfill(2)
        _add(ir, "TipoDocIR", tipo_doc_ref)
        numero_ref = _getv(referencia_doc, "numero") or _getv(referencia_doc, "clave") or ""
        _add(ir, "Numero", _safe(numero_ref, 50))
        fecha_ref = _getv(referencia_doc, "fecha")
        if fecha_ref and hasattr(fecha_ref, "isoformat"):
            _add(ir, "FechaEmisionIR", fecha_ref.isoformat(timespec="seconds") if hasattr(fecha_ref, "hour") else fecha_ref.isoformat() + "T00:00:00-06:00")
        else:
            _add(ir, "FechaEmisionIR", _rfc3339_now())
        _add(ir, "Codigo", _safe(codigo_referencia, 2))
        _add(ir, "Razon", _safe(razon_referencia, 180))
    else:
        ir = _add(root, "InformacionReferencia")
        tipo_ref = "16" if supplier_id_type == "05" else "99"
        _add(ir, "TipoDocIR", tipo_ref)
        if tipo_ref == "99":
            _add(ir, "TipoDocRefOTRO", "Documento de respaldo de compra")
        inv_num = _getv(purchase, "invoice_number") or "SN"
        _add(ir, "Numero", _safe(inv_num, 50))
        _add(ir, "FechaEmisionIR", _rfc3339_now())
        _add(ir, "Codigo", "04")
        _add(ir, "Razon", _safe(razon_referencia, 180))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


# ═════════════════════════════════════════════════════════════
# FEE builder (Fase 2.2)
# ═════════════════════════════════════════════════════════════
def build_xml_for_fee_v44(
    db: Session, *, sale: Any, sale_details: List[Any],
    clave: str, consecutivo: str, customer: Any,
    moneda: str = "USD", tipo_cambio: str = "1.00",
) -> str:
    schema = SCHEMAS_V44["FEE"]
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")
    _require(issuer, "provider_system_id", "ProveedorSistemas")
    _require(issuer, "economic_activity_code", "CodigoActividadEmisor")
    for f in ("provincia", "canton", "distrito", "barrio", "otras_senas"):
        _require(issuer, f, f"Emisor.{f}")
    if not _has_receptor(customer):
        raise ValueError("FEE requiere un receptor con identificación.")

    ET.register_namespace("", schema["xmlns"])
    ET.register_namespace("xsi", NS_XSI)
    root = ET.Element(f"{{{schema["xmlns"]}}}{schema["root_tag"]}", {f"{{{NS_XSI}}}schemaLocation": schema["schemaLocation"]})

    _add(root, "Clave", clave)
    _add(root, "ProveedorSistemas", _safe(issuer.provider_system_id, 20))
    _add(root, "CodigoActividadEmisor", _zfill(issuer.economic_activity_code, 6))
    _add(root, "NumeroConsecutivo", consecutivo)
    _add(root, "FechaEmision", _rfc3339_now())

    _write_emisor_std(root, issuer)
    _write_receptor(root, customer, "FEE")

    forced = (_getv(sale, "condicion_venta_code") or "").strip()
    cond = forced.zfill(2) if forced else "01"
    _add(root, "CondicionVenta", cond)
    if cond in ("02", "10"):
        plazo = _getv(sale, "credit_days")
        if plazo and int(plazo) > 0:
            _add(root, "PlazoCredito", str(int(plazo)))

    detalle = _add(root, "DetalleServicio")
    acc = _ResumenAccumulators()
    _pmap = _prefetch_products(db, sale_details)
    for i, d in enumerate(sale_details, start=1):
        _process_detail_line(db, detalle, d, i, "FEE", acc, products_map=_pmap)

    resumen = _add(root, schema["resumen_tag"])
    mon = _add(resumen, "CodigoTipoMoneda")
    _add(mon, "CodigoMoneda", _safe(moneda, 3))
    _add(mon, "TipoCambio", tipo_cambio)
    total_comprobante_out: list[Decimal] = []
    acc.write_resumen(resumen, total_comprobante_out, doc_type="FEE")
    total_comprobante = total_comprobante_out[0]
    _write_medio_pago(resumen, sale, total_comprobante)
    _add(resumen, "TotalComprobante", str(total_comprobante))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")