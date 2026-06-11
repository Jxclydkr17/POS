"""
diagnostico_envio2.py — Aísla si un PROXY / VPN / antivirus está rompiendo el
envío a Hacienda.

Corre desde D:\\POS con el venv activado:

    python diagnostico_envio2.py

No envía nada real. Compara la misma petición:
  (A) como la hace el sistema hoy (respetando proxy del entorno)
  (B) FORZANDO sin proxy y sin usar variables de entorno
Si (B) funciona y (A) no, el culpable es un proxy/VPN/antivirus.
Al final imprime un comando curl para que pruebes por fuera de Python.
"""
import os
import requests

from app.einvoice.hacienda_client import get_hacienda_client, _URLS
from app.core.credentials import hacienda_env

SEP = "=" * 70


def mask(t):
    return f"{t[:10]}...{t[-6:]} (len={len(t)})" if t else "(vacío)"


def main():
    env = hacienda_env()
    urls = _URLS.get(env, _URLS["sandbox"])
    url = f"{urls['api']}/recepcion"

    print(SEP)
    print("VARIABLES DE PROXY EN EL ENTORNO:")
    found = False
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
              "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
        if os.environ.get(k):
            print(f"  {k} = {os.environ[k]}")
            found = True
    if not found:
        print("  (ninguna variable de proxy en el entorno)")

    # Lo que 'requests' detecta del sistema (incluye proxy de Windows)
    sys_proxies = requests.utils.getproxies()
    print(f"  Proxies del sistema que requests usaría: {sys_proxies or '(ninguno)'}")
    print(SEP)

    token = get_hacienda_client()._get_token()
    print(f"Token: {mask(token)}")
    headers = {"Authorization": f"Bearer {token.strip()}",
               "Content-Type": "application/json"}
    body = {"clave": "0" * 50, "fecha": "2026-06-10T08:00:00-06:00",
            "emisor": {"tipoIdentificacion": "02", "numeroIdentificacion": "3101000000"},
            "comprobanteXml": "PHRlc3Qv"}
    print(SEP)

    # ── (A) Como hoy: Session normal, respeta entorno/proxy ──
    print("(A) POST respetando proxy/entorno (trust_env=True):")
    sa = requests.Session()
    try:
        ra = sa.post(url, json=body, headers=headers, timeout=30, allow_redirects=False)
        print(f"    -> HTTP {ra.status_code} | {ra.text[:200]}")
    except Exception as e:
        print(f"    -> ERROR: {e}")
    print(SEP)

    # ── (B) Forzado SIN proxy y SIN variables de entorno ──
    print("(B) POST FORZANDO sin proxy (trust_env=False, proxies vacíos):")
    sb = requests.Session()
    sb.trust_env = False
    try:
        rb = sb.post(url, json=body, headers=headers, timeout=30,
                     allow_redirects=False, proxies={"http": None, "https": None})
        print(f"    -> HTTP {rb.status_code} | {rb.text[:200]}")
        if rb.status_code != 403:
            print("    *** ¡CAMBIÓ! El proxy/entorno era el problema. ***")
    except Exception as e:
        print(f"    -> ERROR: {e}")
    print(SEP)

    # ── Comando curl para probar por fuera de Python ──
    print("PROBÁ ESTO TAMBIÉN EN POWERSHELL (curl nativo, fuera de Python).")
    print("Si curl da el MISMO error, el problema es de red/cuenta, no del código:")
    print()
    print(f'curl.exe -i -X POST "{url}" ^')
    print('  -H "Authorization: Bearer PEGA_AQUI_EL_TOKEN" ^')
    print('  -H "Content-Type: application/json" ^')
    print('  -d "{\\"clave\\":\\"' + "0"*50 + '\\",\\"fecha\\":\\"2026-06-10T08:00:00-06:00\\",'
          '\\"emisor\\":{\\"tipoIdentificacion\\":\\"02\\",\\"numeroIdentificacion\\":\\"3101000000\\"},'
          '\\"comprobanteXml\\":\\"PHRlc3Qv\\"}"')
    print()
    print("Token completo para el curl (copialo):")
    print(token)
    print(SEP)
    print("Pegá TODA esta salida en el chat.")


if __name__ == "__main__":
    main()