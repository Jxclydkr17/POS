# Schemas XSD — Hacienda Costa Rica v4.4

Este directorio debe contener los XSD oficiales de Hacienda para validación offline.

## Cómo obtenerlos

Descargá cada archivo desde el CDN de Hacienda:

```bash
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/tiqueteElectronico.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaCreditoElectronica.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaDebitoElectronica.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaCompra.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronicaExportacion.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/reciboElectronicoPago.xsd
curl -O https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/tiposComunes.xsd
```

## Estructura esperada

```
app/einvoice/schemas/v4.4/
├── README.md  (este archivo)
├── facturaElectronica.xsd
├── tiqueteElectronico.xsd
├── notaCreditoElectronica.xsd
├── notaDebitoElectronica.xsd
├── facturaElectronicaCompra.xsd
├── facturaElectronicaExportacion.xsd
└── reciboElectronicoPago.xsd
```

## Nota

Si los XSD no están presentes, la validación se omite silenciosamente
(el flujo no se bloquea). Pero es muy recomendable tenerlos para atrapar
errores antes de enviar a Hacienda.

## Dependencia

Requiere `lxml` instalado:
```bash
pip install lxml
```