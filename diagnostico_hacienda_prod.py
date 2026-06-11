#!/usr/bin/env python
"""
diagnostico_hacienda_prod.py — Confirma, SIN RIESGO, si tu pipeline funciona
contra el endpoint SANO de PRODUCCIÓN, para aislar que el 403 es solo del sandbox.

    (venv) PS D:\\POS> python diagnostico_hacienda_prod.py

╔══════════════════════════════════════════════════════════════════════╗
║  ¿POR QUÉ ES SEGURO?                                                  ║
║  - La prueba principal es un GET de consulta de estado: es de SOLO    ║
║    LECTURA, no crea ni registra absolutamente nada.                   ║
║  - Las pruebas POST mandan un body VACÍO ({}). Un JSON vacío NO puede ║
║    convertirse en un comprobante válido: rebota en validación (400)   ║
║    sin efecto fiscal. No se emite ninguna factura.                    ║
╚══════════════════════════════════════════════════════════════════════╝

CREDENCIALES DE PRODUCCIÓN (son DISTINTAS de las de stag):
  El usuario de prod suele ser  cpj-...@prod.comprobanteselectronicos.go.cr
  y la contraseña la generás/obtenés en ATV/TRIBU-CR (no es la de stag).

  Proveelas de una de estas formas:
    1) Variables de entorno  HACIENDA_PROD_USER  y  HACIENDA_PROD_PASSWORD
    2) Si no, el script te las pide de forma interactiva (la clave oculta).

  Saltar la confirmación:  python diagnostico_hacienda_prod.py --yes
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import sys

import requests

SKIP_CONFIRM = "--yes" in sys.argv or "-y" in sys.argv

# ──────────────────────────────────────────────────────────────
# Config FORZADA a producción
# ──────────────────────────────────────────────────────────────
CFG = {
    "idp": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token",
    "api": "https://api.comprobanteselectronicos.go.cr/recepcion/v1",
    "client_id": "api-prod",
}
RECEPCION_URL = f"{CFG['api']}/recepcion"
# Clave ficticia de 50 dígitos solo para el GET de consulta (read-only).
DUMMY_CLAVE = "50601011600310112345600100010100000000011900000000"
GET_URL = f"{CFG['api']}/recepcion/{DUMMY_CLAVE}"
TIMEOUT = 30

print("═" * 70)
print(" DIAGNÓSTICO DE *** PRODUCCIÓN *** (sin riesgo: GET read-only + POST body vacío)")
print("═" * 70)
print(f"[cfg]  idp      = {CFG['idp']}")
print(f"[cfg]  api      = {CFG['api']}")
print(f"[cfg]  recepcion= {RECEPCION_URL}")
print(f"[cfg]  clientid = {CFG['client_id']}")


# ──────────────────────────────────────────────────────────────
# Credenciales de PRODUCCIÓN (nunca caemos a las de stag por accidente)
# ──────────────────────────────────────────────────────────────
def get_prod_creds() -> tuple[str, str]:
    user = os.getenv("HACIENDA_PROD_USER", "").strip()
    pwd = os.getenv("HACIENDA_PROD_PASSWORD", "").strip()

    if user and pwd:
        print(f"[creds] Tomadas de HACIENDA_PROD_USER/PASSWORD | user={user!r}")
    else:
        print("[creds] No encontré HACIENDA_PROD_USER/PASSWORD en el entorno.")
        print("[creds] Ingresalas manualmente (son las de PRODUCCIÓN, no las de stag):")
        try:
            user = input("        Usuario prod: ").strip()
            pwd = getpass.getpass("        Clave   prod: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\n[cancelado]")

    if not user or not pwd:
        sys.exit("[FATAL] Falta usuario o clave de producción.")

    if "stag" in user.lower():
        print("\n⚠⚠  OJO: el usuario contiene 'stag'. Parecen credenciales de SANDBOX,")
        print("        no de producción. El IdP de prod (realm rut) las va a rechazar.")
        print("        El usuario de prod suele ser ...@prod.comprobanteselectronicos.go.cr\n")

    return user, pwd


def confirm() -> None:
    if SKIP_CONFIRM:
        return
    print("\nEsto golpea el ambiente de PRODUCCIÓN de Hacienda.")
    print("Es seguro (GET de consulta + POST con body vacío, sin efecto fiscal),")
    print("pero confirmá para continuar.")
    try:
        ans = input("¿Continuar? [s/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\n[cancelado]")
    if ans not in ("s", "si", "sí", "y", "yes"):
        sys.exit("[cancelado por el usuario]")


# ──────────────────────────────────────────────────────────────
# Token
# ──────────────────────────────────────────────────────────────
def get_token(user: str, pwd: str) -> tuple[str, str]:
    data = {
        "grant_type": "password",
        "client_id": CFG["client_id"],
        "username": user,
        "password": pwd,
    }
    r = requests.post(
        CFG["idp"], data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    print(f"\n[token] IdP prod HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"[token] Cuerpo: {r.text[:400]}")
        sys.exit(
            "[FATAL] El IdP de PRODUCCIÓN no devolvió token.\n"
            "        Casi seguro estás usando credenciales de stag, o todavía no\n"
            "        generaste las de producción en ATV/TRIBU-CR. Son distintas."
        )
    j = r.json()
    tok = (j.get("access_token") or "").strip()
    ttype = (j.get("token_type") or "bearer").strip()
    print(f"[token] token_type = {ttype!r} | expires_in = {j.get('expires_in')}")
    print(f"[token] longitud access_token = {len(tok)} chars")
    return tok, ttype


def inspect_jwt(tok: str) -> None:
    parts = tok.split(".")
    if len(parts) != 3:
        print(f"[jwt]  ⚠ El token NO tiene 3 segmentos ({len(parts)}).")
        return
    try:
        for name, idx in (("header", 0), ("payload", 1)):
            seg = parts[idx]
            seg += "=" * (-len(seg) % 4)
            obj = json.loads(base64.urlsafe_b64decode(seg))
            if name == "header":
                print(f"[jwt]  header = {obj}")
            else:
                print(f"[jwt]  iss = {obj.get('iss')} | aud = {obj.get('aud')} "
                      f"| azp = {obj.get('azp')} | exp = {obj.get('exp')}")
    except Exception as e:
        print(f"[jwt]  ⚠ No pude decodificar el JWT: {e}")


# ──────────────────────────────────────────────────────────────
# Pruebas
# ──────────────────────────────────────────────────────────────
def probe_post(label: str, headers: dict) -> tuple[int, str]:
    try:
        r = requests.post(RECEPCION_URL, json={}, headers=headers, timeout=TIMEOUT)
    except Exception as e:
        print(f"[{label}] EXCEPCIÓN: {e}")
        return -1, str(e)
    print(f"[{label}] HTTP {r.status_code} | {r.text[:300].replace(chr(10), ' ')}")
    return r.status_code, r.text


def probe_get(label: str, headers: dict) -> tuple[int, str]:
    try:
        r = requests.get(GET_URL, headers=headers, timeout=TIMEOUT)
    except Exception as e:
        print(f"[{label}] EXCEPCIÓN: {e}")
        return -1, str(e)
    print(f"[{label}] HTTP {r.status_code} | {r.text[:300].replace(chr(10), ' ')}")
    return r.status_code, r.text


def main() -> None:
    user, pwd = get_prod_creds()
    confirm()
    tok, ttype = get_token(user, pwd)
    inspect_jwt(tok)
    print("─" * 70)

    ct = {"Content-Type": "application/json"}
    auth = {"Authorization": f"{ttype} {tok}"}

    print("PRUEBA E — GET consulta de estado (SOLO LECTURA, clave ficticia):")
    code_get, body_get = probe_get("E", {**auth})

    print("\nPRUEBA A — POST /recepcion, token REAL, body vacío:")
    code_real, body_real = probe_post("A", {**auth, **ct})

    print("\nPRUEBA B — POST token BASURA ('xxx'):")
    code_junk, _ = probe_post("B", {"Authorization": "Bearer xxx", **ct})

    print("\nPRUEBA C — POST sin Authorization:")
    code_none, _ = probe_post("C", {**ct})

    # ── Veredicto ──────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("VEREDICTO (producción)")
    print("═" * 70)

    aws_err_real = "missing equal-sign" in (body_real or "")
    aws_err_get = "missing equal-sign" in (body_get or "")
    auth_paso = (
        code_get in (200, 404, 400) or          # GET llegó al backend
        code_real in (200, 202, 400)            # POST pasó auth (400 = body vacío)
    )

    if auth_paso and not aws_err_real:
        print("✅ AUTENTICACIÓN OK EN PRODUCCIÓN. El gateway aceptó tu Bearer.")
        print("   - GET de consulta y/o POST con body vacío llegaron al backend.")
        print("   - El 400/404 es esperado (clave ficticia / body vacío): SIN efecto fiscal.")
        print("   → Tu pipeline está bien. El 403 es EXCLUSIVO del sandbox.")
        print("   → No estás bloqueado para producción.")
    elif aws_err_real or aws_err_get:
        if code_junk == code_real:
            print("❗ PRODUCCIÓN TAMBIÉN responde en modo AWS_IAM (token basura = mismo error).")
            print("   → No es solo el sandbox: es un problema GLOBAL de Hacienda ahora mismo.")
            print("   → No salgas a producción hasta que se normalice. Reportá a la DGT.")
        else:
            print("❗ El gateway de prod rechaza el Bearer como SigV4. Revisá esquema (A vs C).")
    elif code_real == 401 or code_get == 401:
        print("⚠ 401: el autorizador de prod validó y RECHAZÓ tu token.")
        print("   Casi seguro estás usando credenciales que no son de producción,")
        print("   o el aud/realm no corresponde. Verificá las credenciales de prod.")
    else:
        print(f"❓ Resultado no clásico. Revisá los cuerpos de arriba.")

    print("\nResumen de códigos:")
    print(f"   E get={code_get}  A post-real={code_real}  B basura={code_junk}  C sin-auth={code_none}")


if __name__ == "__main__":
    main()