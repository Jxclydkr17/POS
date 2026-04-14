# app/core/rate_limiter.py
"""
FASE 2 — Fix 2.2: Rate limiter en memoria (reemplaza archivos JSON).

Problema anterior:
  Cada request leía y escribía un archivo JSON completo con threading.Lock.
  En un POS con varias llamadas concurrentes, esto era un cuello de botella
  de I/O en disco. Además, si la app se cerraba durante la escritura, el
  archivo se corrompía y se perdían los datos.

Solución:
  Rate limiter 100% en memoria con dict + deque. Para un POS de escritorio
  que corre como proceso único (uvicorn single-worker en daemon thread),
  la memoria es el storage ideal:
    - Sin I/O de disco → sin cuello de botella
    - Sin archivos → sin corrupción
    - Se resetea al reiniciar → comportamiento correcto para rate limiting
    - threading.Lock solo protege operaciones en memoria (microsegundos)

Uso:
    from app.core.rate_limiter import rate_limit

    @router.post("/", dependencies=[rate_limit("sales_create", 60, 60)])
    def create_sale(...):
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════
# Storage en memoria: {group: {ip: deque([timestamp, ...])}}
# deque con maxlen limita automáticamente el tamaño
# ═══════════════════════════════════════════════════════════════
_buckets: dict[str, dict[str, deque]] = defaultdict(dict)

# Límite global de IPs trackeadas por grupo (prevención de memory leak)
_MAX_IPS_PER_GROUP = 5000


def _cleanup_expired(group: str, window_seconds: int):
    """
    Limpia timestamps expirados de un grupo.
    Llamado periódicamente dentro del lock.
    """
    cutoff = time.monotonic() - window_seconds
    group_data = _buckets.get(group, {})

    # Limpiar timestamps viejos de cada IP
    dead_ips = []
    for ip, timestamps in group_data.items():
        # deque: remover desde la izquierda (más viejo)
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if not timestamps:
            dead_ips.append(ip)

    # Remover IPs sin timestamps
    for ip in dead_ips:
        del group_data[ip]


def _evict_oldest_ips(group: str):
    """
    Si hay demasiadas IPs trackeadas, elimina la mitad más vieja.
    Previene memory leak si alguien hace scanning de IPs.
    """
    group_data = _buckets.get(group, {})
    if len(group_data) <= _MAX_IPS_PER_GROUP:
        return

    # Ordenar por timestamp más reciente (ascendente) y quedarse con la mitad más nueva
    sorted_ips = sorted(
        group_data.items(),
        key=lambda x: x[1][-1] if x[1] else 0,
    )
    keep_from = len(sorted_ips) // 2
    for ip, _ in sorted_ips[:keep_from]:
        del group_data[ip]

    logger.debug(f"Rate limiter ({group}): evicted {keep_from} IPs (memory limit)")


# ═══════════════════════════════════════════════════════════════
# Dependencia FastAPI
# ═══════════════════════════════════════════════════════════════

def rate_limit(
    group: str = "default",
    max_requests: int = 30,
    window_seconds: int = 60,
) -> Callable:
    """
    Retorna una dependencia FastAPI que aplica rate limiting por IP.

    Args:
        group: nombre del grupo (aislamiento entre endpoints)
        max_requests: requests máximos en la ventana
        window_seconds: duración de la ventana en segundos

    Ejemplo:
        @router.post("/", dependencies=[rate_limit("sales_create", 60, 60)])
    """
    def _limiter(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        with _lock:
            # Inicializar grupo si no existe
            if group not in _buckets:
                _buckets[group] = {}

            group_data = _buckets[group]

            # Inicializar IP si no existe
            if client_ip not in group_data:
                group_data[client_ip] = deque()

            timestamps = group_data[client_ip]

            # Limpiar timestamps fuera de la ventana
            cutoff = now - window_seconds
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            # Verificar límite
            if len(timestamps) >= max_requests:
                # Calcular tiempo hasta que el request más viejo expire
                oldest = timestamps[0]
                retry_at = oldest + window_seconds
                retry_secs = max(1, int(retry_at - now))

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Demasiadas solicitudes. Límite: {max_requests} "
                        f"cada {window_seconds}s. Reintente en {retry_secs}s."
                    ),
                    headers={"Retry-After": str(retry_secs)},
                )

            # Registrar este request
            timestamps.append(now)

            # Limpieza periódica (cada ~100 requests por grupo)
            total_entries = sum(len(ts) for ts in group_data.values())
            if total_entries % 100 == 0:
                _cleanup_expired(group, window_seconds)
                _evict_oldest_ips(group)

    return Depends(_limiter)