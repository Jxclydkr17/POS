from fastapi import APIRouter, Depends, HTTPException
import requests
from functools import lru_cache
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/locations", tags=["Locations"])

BASE = "https://ubicaciones.paginasweb.cr"

def _get_json(url: str):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error consultando ubicaciones: {e}")

@lru_cache(maxsize=64)
def _cached(url: str):
    return _get_json(url)

@router.get("/provinces")
def provinces(user: dict = Depends(get_current_user)):
    return _cached(f"{BASE}/provincias.json")

@router.get("/provinces/{province_id}/cantons")
def cantons(province_id: str, user: dict = Depends(get_current_user)):
    return _cached(f"{BASE}/provincia/{province_id}/cantones.json")

@router.get("/provinces/{province_id}/cantons/{canton_id}/districts")
def districts(province_id: str, canton_id: str, user: dict = Depends(get_current_user)):
    return _cached(f"{BASE}/provincia/{province_id}/canton/{canton_id}/distritos.json")
