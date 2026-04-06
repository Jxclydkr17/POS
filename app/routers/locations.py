from fastapi import APIRouter, Depends, HTTPException
import requests
import time
import threading
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/locations", tags=["Locations"])

BASE = "https://ubicaciones.paginasweb.cr"


# ── FASE 4 — Fix 4.4: Caché con TTL en vez de lru_cache eterno ──
# lru_cache nunca expiraba: si el API externo fallaba, el error quedaba
# cacheado para siempre. Ahora los datos expiran cada 24h (razonable
# para datos geográficos que casi nunca cambian).
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 86400  # 24 horas en segundos


def _get_json(url: str):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error consultando ubicaciones: {e}")


def _cached(url: str):
    now = time.monotonic()
    with _cache_lock:
        if url in _cache:
            cached_at, data = _cache[url]
            if (now - cached_at) < _CACHE_TTL:
                return data

    # Fuera del lock: hacer el request HTTP
    data = _get_json(url)

    with _cache_lock:
        _cache[url] = (now, data)
    return data


@router.get("/provinces")
def provinces(user: dict = Depends(get_current_user)):
    return _cached(f"{BASE}/provincias.json")

@router.get("/provinces/{province_id}/cantons")
def cantons(province_id: str, user: dict = Depends(get_current_user)):
    return _cached(f"{BASE}/provincia/{province_id}/cantones.json")

@router.get("/provinces/{province_id}/cantons/{canton_id}/districts")
def districts(province_id: str, canton_id: str, user: dict = Depends(get_current_user)):
    return _cached(f"{BASE}/provincia/{province_id}/canton/{canton_id}/distritos.json")