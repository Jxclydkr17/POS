#!/usr/bin/env python
"""
diagnostico_hacienda.py — Aísla la causa del 403 de Hacienda.

Corré esto desde la raíz del proyecto (D:\\POS) con el venv activo:

    (venv) PS D:\\POS> python diagnostico_hacienda.py

Qué hace:
  1. Pide el token al IdP usando EXACTAMENTE las mismas credenciales que la app
     (las lee de app.core.credentials -> secure_config/DB y luego .env).
  2. Verifica que el token sea un JWT real (3 segmentos, decodifica el header).
  3. Golpea el endpoint /recepcion con 4 variantes para ver QUIÉN rechaza:
        A) token REAL          -> ¿el gateway valida el Bearer?
        B) token BASURA        -> ¿el gateway siquiera mira el token?
        C) SIN Authorization   -> ¿el recurso es IAM / ruta inexistente?
        D) "bearer" minúscula  -> ¿es sensible a mayúsculas el esquema?
  4. Imprime un veredicto claro.

NO envía ningún comprobante con valor fiscal: manda un body vacío a propósito,
solo para ver en qué capa se cae (auth vs. validación de cuerpo).
"""
from __future__ import annotations

import base64
import json
import sys

import requests

# ──────────────────────────────────────────────────────────────
# 1. Credenciales: mismas que usa la app
# ──────────────────────────────────────────────────────────────
try:
    from app.core.credentials import (
        hacienda_env, hacienda_user, hacienda_password,
    )
    ENV = hacienda_env()
    USER = hacienda_user()
    PASSWORD = hacienda_password()
    print(f"[creds] Leídas desde app.core.credentials | env={ENV} | user={USER!r}")
except Exception as e:
    print(f"[creds] No pude importar app.core.credentials ({e}).")
    print("[creds] Usá variables de entorno HACIENDA_ENV/USER/PASSWORD o editá el script.")
    import os
    ENV = os.getenv("HACIENDA_ENV", "sandbox")
    USER = os.getenv("HACIENDA_USER", "")
    PASSWORD = os.getenv("HACIENDA_PASSWORD", "")

if not USER or not PASSWORD:
    sys.exit("[FATAL] Falta usuario o contraseña de Hacienda.")

_URLS = {
    "sandbox": {
        "idp": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut-stag/protocol/openid-connect/token",
        "api": "https://api.comprobanteselectronicos.go.cr/recepcion-sandbox/v1",
        "client_id": "api-stag",
    },
    "production": {
        "idp": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token",
        "api": "https://api.comprobanteselectronicos.go.cr/recepcion/v1",
        "client_id": "api-prod",
    },
}
cfg = _URLS.get(ENV, _URLS["sandbox"])
RECEPCION_URL = f"{cfg['api']}/recepcion"
TIMEOUT = 30

print(f"[cfg]  idp      = {cfg['idp']}")
print(f"[cfg]  api      = {cfg['api']}")
print(f"[cfg]  recepcion= {RECEPCION_URL}")
print(f"[cfg]  clientid = {cfg['client_id']}")
print("─" * 70)


# ──────────────────────────────────────────────────────────────
# 2. Token
# ──────────────────────────────────────────────────────────────
def get_token() -> tuple[str, str]:
    data = {
        "grant_type": "password",
        "client_id": cfg["client_id"],
        "username": USER,
        "password": PASSWORD,
    }
    r = requests.post(
        cfg["idp"], data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    print(f"[token] IdP HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"[token] Cuerpo: {r.text[:400]}")
        sys.exit("[FATAL] El IdP NO devolvió token. El problema es de credenciales/IdP, "
                 "no del endpoint de recepción. Revisá usuario/clave/realm/env.")
    j = r.json()
    tok = (j.get("access_token") or "").strip()
    ttype = (j.get("token_type") or "bearer").strip()
    print(f"[token] token_type = {ttype!r} | expires_in = {j.get('expires_in')}")
    print(f"[token] longitud access_token = {len(tok)} chars")
    return tok, ttype


def inspect_jwt(tok: str) -> None:
    parts = tok.split(".")
    if len(parts) != 3:
        print(f"[jwt]  ⚠ El token NO tiene 3 segmentos ({len(parts)}). No parece un JWT válido.")
        return
    try:
        head_seg = parts[0]
        head_seg += "=" * (-len(head_seg) % 4)  # padding base64url
        header = json.loads(base64.urlsafe_b64decode(head_seg))
        print(f"[jwt]  header = {header}")
        body_seg = parts[1]
        body_seg += "=" * (-len(body_seg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body_seg))
        print(f"[jwt]  iss = {payload.get('iss')}")
        print(f"[jwt]  aud = {payload.get('aud')}")
        print(f"[jwt]  azp = {payload.get('azp')}")
        print(f"[jwt]  exp = {payload.get('exp')}")
    except Exception as e:
        print(f"[jwt]  ⚠ No pude decodificar el JWT: {e}")


# ──────────────────────────────────────────────────────────────
# 3. Pruebas contra /recepcion
# ──────────────────────────────────────────────────────────────
def probe(label: str, headers: dict) -> tuple[int, str]:
    # Body vacío a propósito: solo queremos ver en qué capa nos rechaza.
    try:
        r = requests.post(RECEPCION_URL, json={}, headers=headers, timeout=TIMEOUT)
    except Exception as e:
        print(f"[{label}] EXCEPCIÓN: {e}")
        return -1, str(e)
    body = r.text[:300].replace("\n", " ")
    print(f"[{label}] HTTP {r.status_code} | {body}")
    return r.status_code, r.text


def main() -> None:
    tok, ttype = get_token()
    inspect_jwt(tok)
    print("─" * 70)

    ct = {"Content-Type": "application/json"}

    print("PRUEBA A — token REAL, esquema tal cual lo manda la app:")
    code_real, body_real = probe("A", {"Authorization": f"{ttype} {tok}", **ct})

    print("\nPRUEBA B — token BASURA ('xxx'):")
    code_junk, _ = probe("B", {"Authorization": "Bearer xxx", **ct})

    print("\nPRUEBA C — SIN header Authorization:")
    code_none, _ = probe("C", {**ct})

    print("\nPRUEBA D — esquema 'bearer' en minúscula con token real:")
    code_lower, _ = probe("D", {"Authorization": f"bearer {tok}", **ct})

    # ── Veredicto ──────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("VEREDICTO")
    print("═" * 70)

    aws_sig_err = "missing equal-sign" in (body_real or "")

    if code_real in (200, 202, 400):
        print("✅ La AUTENTICACIÓN PASÓ. El gateway aceptó tu Bearer.")
        if code_real == 400:
            print("   El 400 es esperado: mandamos body vacío. Tu token y endpoint")
            print("   están BIEN. El 403 original NO era de auth; revisá el cuerpo/")
            print("   payload del comprobante que arma la app.")
    elif aws_sig_err:
        print("❗ El gateway de AWS rechazó el Bearer como si esperara una firma")
        print("   SigV4 (error 'missing equal-sign').")
        if code_junk == code_real:
            print("   → El token BASURA da el MISMO error que el real: el gateway NI")
            print("     SIQUIERA está mirando tu token. NO es problema de tu token.")
            print("     Es el ENDPOINT/recurso de Hacienda (modo IAM o autorizador caído).")
            print("     CAUSA: lado Hacienda. No hay fix en tu código. Reintentá luego /")
            print("     escribí a soporte DGT. NO cambiés la URL: es la oficial.")
        else:
            print("   → El token basura da OTRO resultado: el gateway sí distingue.")
            print("     Revisá esquema/mayúsculas (compará prueba A vs D).")
    elif code_real in (401,):
        print("⚠ 401: el autorizador SÍ está validando y RECHAZÓ tu token.")
        print("   Problema del lado tuyo: env/realm equivocado, token de otro")
        print("   ambiente, aud/azp incorrecto o clave vencida. Revisá que el env")
        print("   del token coincida con el env del endpoint (stag vs prod).")
    else:
        print(f"❓ Resultado no clásico (HTTP {code_real}). Revisá el cuerpo arriba.")

    print("\nResumen de códigos:")
    print(f"   A real={code_real}  B basura={code_junk}  C sin-auth={code_none}  D minúscula={code_lower}")


if __name__ == "__main__":
    main()