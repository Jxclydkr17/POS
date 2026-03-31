from app.einvoice.xml_builder_v44 import (
    build_xml_for_sale_v44,
    build_xml_for_rep_v44,
    build_xml_for_nc_v44,
    build_xml_for_nd_v44,
    build_xml_for_fec_v44,
    build_xml_for_fee_v44,
)

# ✅ FASE 5.5: Acepta referencia_doc opcional para FE (obligatorio con exon código 11)
def build_xml_for_sale(db, *, sale, sale_details, clave, consecutivo, customer=None,
                       referencia_doc=None, codigo_referencia="04", razon_referencia="Referencia"):
    return build_xml_for_sale_v44(
        db,
        sale=sale,
        sale_details=sale_details,
        clave=clave,
        consecutivo=consecutivo,
        customer=customer,
        referencia_doc=referencia_doc,
        codigo_referencia=codigo_referencia,
        razon_referencia=razon_referencia,
    )

def build_xml_for_rep(db, *, payment, customer, referenced_einvoices, clave, consecutivo,
                      condicion_venta_rep="11", codigo_referencia="01", razon_referencia="Pago registrado"):
    return build_xml_for_rep_v44(
        db,
        payment=payment,
        customer=customer,
        referenced_einvoices=referenced_einvoices,
        clave=clave,
        consecutivo=consecutivo,
        condicion_venta_rep=condicion_venta_rep,
        codigo_referencia=codigo_referencia,
        razon_referencia=razon_referencia,
    )

def build_xml_for_nc(db, *, sale, sale_details, clave, consecutivo, customer=None,
                     original_einv, razon="Anulación de comprobante"):
    return build_xml_for_nc_v44(
        db,
        sale=sale,
        sale_details=sale_details,
        clave=clave,
        consecutivo=consecutivo,
        customer=customer,
        original_einv=original_einv,
        razon=razon,
    )

def build_xml_for_nd(db, *, sale, sale_details, clave, consecutivo, customer=None,
                     original_einv, razon="Corrección de monto", codigo_referencia="02"):
    return build_xml_for_nd_v44(
        db,
        sale=sale,
        sale_details=sale_details,
        clave=clave,
        consecutivo=consecutivo,
        customer=customer,
        original_einv=original_einv,
        razon=razon,
        codigo_referencia=codigo_referencia,
    )

def build_xml_for_fec(db, *, purchase, purchase_details, supplier, clave, consecutivo,
                      condicion_venta="01", referencia_doc=None,
                      razon_referencia="Compra a proveedor", codigo_referencia="04"):
    return build_xml_for_fec_v44(
        db,
        purchase=purchase,
        purchase_details=purchase_details,
        supplier=supplier,
        clave=clave,
        consecutivo=consecutivo,
        condicion_venta=condicion_venta,
        referencia_doc=referencia_doc,
        razon_referencia=razon_referencia,
        codigo_referencia=codigo_referencia,
    )

def build_xml_for_fee(db, *, sale, sale_details, clave, consecutivo, customer,
                      moneda="USD", tipo_cambio="1.00"):
    return build_xml_for_fee_v44(
        db,
        sale=sale,
        sale_details=sale_details,
        clave=clave,
        consecutivo=consecutivo,
        customer=customer,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
    )