"""
diagnostico_envio.py — Diagnóstico del envío a Hacienda.

Corre desde la raíz del proyecto (D:\\POS) con el venv activado:

    python diagnostico_envio.py

NO envía ningún comprobante real: solo obtiene el token con tus credenciales
y prueba el endpoint de recepción con una petición mínima, mostrando la URL
final, si hay redirects, los headers y la respuesta cruda de Hacienda/AWS.
Esto revela por qué AWS responde 403 "Invalid key=value pair...".
"""
import json
import requests

from app.einvoice.hacienda_client import get_hacienda_client, _URLS
from app.core.credentials import hacienda_env

SEP = "=" * 70


def mask(tok: str) -> str:
    if not tok:
        return "(vacío)"
    return f"{tok[:12]}...{tok[-8:]}  (largo={len(tok)})"


def main():
    env = hacienda_env()
    urls = _URLS.get(env, _URLS["sandbox"])
    print(SEP)
    print(f"Ambiente: {env}")
    print(f"API base: {urls['api']}")
    print(f"IDP:      {urls['idp']}")
    print(SEP)

    # ── 1. Obtener token (usa tus credenciales reales del sistema) ──
    client = get_hacienda_client()
    token = client._get_token()
    print(f"Token obtenido: {mask(token)}")
    # Chequear caracteres sospechosos
    raros = [c for c in token if c in (" ", "\n", "\r", "\t")]
    print(f"¿Token con espacios/saltos?: {'SÍ -> ' + repr(raros) if raros else 'no'}")
    print(SEP)

    url = f"{urls['api']}/recepcion"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
    }
    # Body mínimo solo para provocar la respuesta del endpoint (no es un
    # comprobante válido; si la AUTENTICACIÓN pasa, Hacienda responderá 400
    # por datos, NO 403 por el header).
    body = {
        "clave": "0" * 50,
        "fecha": "2026-06-10T08:00:00-06:00",
        "emisor": {"tipoIdentificacion": "02", "numeroIdentificacion": "3101000000"},
        "comprobanteXml": "PHRlc3Qv",  # "<test/>" en base64
    }

    print("Headers enviados:")
    for k, v in headers.items():
        print(f"  {k}: {'Bearer ' + mask(token) if k == 'Authorization' else v}")
    print(SEP)

    # ── 2. POST SIN seguir redirects, para detectarlos ──
    print(f"POST {url}   (allow_redirects=False)")
    try:
        r = requests.post(url, json=body, headers=headers, timeout=30, allow_redirects=False)
    except Exception as e:
        print("ERROR de conexión:", e)
        return
    print(f"  -> HTTP {r.status_code}")
    if r.is_redirect or "Location" in r.headers:
        print(f"  -> REDIRECT a: {r.headers.get('Location')}")
    for h in ("Location", "x-amzn-ErrorType", "x-amzn-RequestId", "WWW-Authenticate"):
        if h in r.headers:
            print(f"  -> {h}: {r.headers[h]}")
    print(f"  -> Body: {r.text[:600]}")
    print(SEP)

    # ── 3. Probar variante CON barra final ──
    url2 = url + "/"
    print(f"POST {url2}   (variante con barra final)")
    try:
        r2 = requests.post(url2, json=body, headers=headers, timeout=30, allow_redirects=False)
        print(f"  -> HTTP {r2.status_code}")
        if "Location" in r2.headers:
            print(f"  -> REDIRECT a: {r2.headers.get('Location')}")
        print(f"  -> Body: {r2.text[:400]}")
    except Exception as e:
        print("ERROR:", e)
    print(SEP)

    # ── 4. GET de prueba al endpoint de consulta (otra ruta, mismo auth) ──
    url3 = f"{urls['api']}/recepcion/{'0'*50}"
    print(f"GET  {url3}   (consulta de estado, mismo token)")
    try:
        r3 = requests.get(url3, headers={"Authorization": headers["Authorization"]},
                          timeout=30, allow_redirects=False)
        print(f"  -> HTTP {r3.status_code}")
        print(f"  -> Body: {r3.text[:400]}")
    except Exception as e:
        print("ERROR:", e)
    print(SEP)
    print("Listo. Pegá TODA esta salida en el chat.")


if __name__ == "__main__":
    main()