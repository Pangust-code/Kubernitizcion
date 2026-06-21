"""
Health checks de la aplicación.

En producción necesitas DOS endpoints distintos:

  /health  → Liveness probe
    "¿El proceso está vivo?"
    Si falla → el orquestador (Kubernetes, ECS) reinicia el contenedor.
    Debe ser MUY rápido y simple. No verificar dependencias.

  /ready   → Readiness probe
    "¿La app puede recibir tráfico?"
    Si falla → el load balancer deja de enviarle requests a esta instancia.
    Verifica dependencias críticas (Redis, DB, etc.).

Diferencia clave:
  - Una instancia puede estar "viva" pero no "lista" (ej: Redis caído).
  - Durante un rolling update, la nueva instancia empieza a recibir tráfico
    SOLO cuando /ready responde 200.

Ejemplo con Nginx upstream health checks:
  Si /ready devuelve 503 → Nginx saca la instancia del pool automáticamente.

Ejemplo con Kubernetes:
  livenessProbe:  GET /health  cada 10s
  readinessProbe: GET /ready   cada 5s
"""

import logging
import platform
import socket
import time
from datetime import datetime, timezone

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.cache import cache_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Guardamos el tiempo de arranque para calcular el uptime
_startup_time = time.time()


@router.get("/health", status_code=status.HTTP_200_OK)
async def liveness() -> dict:
    """
    Liveness probe — el proceso está vivo y corriendo.

    Este endpoint SIEMPRE debe responder rápido (< 50ms).
    Si la app está en un estado irrecuperable, aquí devolvería 500
    y el orquestador la reiniciaría.
    """
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.time() - _startup_time, 2),
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness() -> JSONResponse:
    """
    Readiness probe — la app está lista para recibir tráfico.

    Verifica que todas las dependencias críticas estén disponibles.
    Si alguna falla, devuelve 503 y el load balancer deja de enviarnos requests.
    """
    checks: dict[str, bool] = {}

    # ── Verificar Redis ───────────────────────────────────────────────────────
    # Redis es crítico: sin él no hay caché ni rate limiting.
    redis_ok = await cache_service.ping()
    checks["redis"] = redis_ok

    # ── Resultado global ──────────────────────────────────────────────────────
    all_healthy = all(checks.values())
    http_status = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    response_body = {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not all_healthy:
        logger.error("Readiness check falló", extra={"checks": checks})

    return JSONResponse(content=response_body, status_code=http_status)


@router.get("/info")
async def app_info() -> dict:
    """
    Información sobre la instancia que está respondiendo.

    Este endpoint es CLAVE para la demo del rolling update:
    muestra qué versión de la app está corriendo en esta instancia específica.

    Cuando haces un rolling update, verás cómo algunas requests responden
    con version="1.0.0" y otras con version="2.0.0" durante la transición.
    """
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,        # Cambia entre instancias durante rolling update
        "environment": settings.ENVIRONMENT,
        "hostname": socket.gethostname(),        # Nombre del contenedor Docker
        "python_version": platform.python_version(),
        "uptime_seconds": round(time.time() - _startup_time, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
