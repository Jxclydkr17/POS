# app/core/rate_limiter.py
"""
FASE 3 — Fix 3.2: Rate limiting reutilizable para endpoints sensibles.

Usa el mismo mecanismo de archivo JSON que el login rate limiter,
pero con configuración independiente por grupo de endpoints.

Uso en routers:
    from app.core.rate_limiter import rate_limit

    @router.post("/", dependencies=[Depends(rate_limit("sales", 30, 60))])
    def create_sale(...):
        ...

Parámetros:
    - group: nombre lógico ("sales", "credits", etc.)
    - max_requests: máximo de requests por ventana
    - window_seconds: duración de la ventana en segundos
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _get_data_path(group: str) -> Path:
    from app.core.config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"rate_limit_{group}.json"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load(group: str) -> dict[str, list[str]]:
    path = _get_data_path(group)
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save(group: str, data: dict[str, list[str]]) -> None:
    path = _get_data_path(group)
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Rate limiter ({group}): no se pudo guardar: {e}")


def rate_limit(
    group: str = "default",
    max_requests: int = 30,
    window_seconds: int = 60,
) -> Callable:
    """
    Retorna una dependencia FastAPI que aplica rate limiting por IP.

    Args:
        group: nombre del grupo (archivos separados por grupo)
        max_requests: requests máximos en la ventana
        window_seconds: tamaño de la ventana en segundos
    """
    def _limiter(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = client_ip

        with _lock:
            now = _now_utc()
            cutoff = now - timedelta(seconds=window_seconds)

            data = _load(group)

            # Filtrar solo timestamps dentro de la ventana
            timestamps = [
                ts for ts in data.get(key, [])
                if datetime.fromisoformat(ts) > cutoff
            ]

            if len(timestamps) >= max_requests:
                oldest = datetime.fromisoformat(timestamps[0])
                retry_at = oldest + timedelta(seconds=window_seconds)
                retry_secs = max(1, int((retry_at - now).total_seconds()))
                data[key] = timestamps
                _save(group, data)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Demasiadas solicitudes. Límite: {max_requests} "
                        f"cada {window_seconds}s. Reintente en {retry_secs}s."
                    ),
                    headers={"Retry-After": str(retry_secs)},
                )

            # Registrar este request
            timestamps.append(now.isoformat())
            data[key] = timestamps

            # Limitar IPs trackeadas (max 5000 por grupo)
            if len(data) > 5000:
                sorted_keys = sorted(
                    data.keys(),
                    key=lambda k: data[k][-1] if data[k] else "",
                )
                data = {k: data[k] for k in sorted_keys[len(sorted_keys) // 2:]}

            _save(group, data)

    return Depends(_limiter)