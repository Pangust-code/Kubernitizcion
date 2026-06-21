"""
Punto de entrada de la aplicación FastAPI.

Aquí se configura:
  - Lifespan: código que corre al arrancar y al apagar la app.
  - Middleware: lógica que envuelve CADA request (métricas, logging, CORS).
  - Routers: los módulos con los endpoints.
  - Prometheus: exposición de métricas en /metrics.

Conceptos importantes para producción:
  - Graceful shutdown: al recibir SIGTERM, terminamos requests en curso.
  - Middleware de métricas: registramos latencia y status de cada request.
  - Structured logging: cada request genera un log JSON con contexto.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.config import settings
from app.observability.logging_config import setup_logging
from app.observability.metrics import (
    app_info,
    http_active_requests,
    http_request_duration_seconds,
    http_requests_total,
)
from app.routers import health, items
from app.services.cache import cache_service

logger = logging.getLogger(__name__)


# ─── Lifespan: startup y shutdown ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Código que corre al ARRANCAR y al APAGAR la aplicación.

    Startup (antes del `yield`):
      - Configurar logging.
      - Verificar conexión con dependencias.
      - Registrar info en métricas.

    Shutdown (después del `yield`):
      - Cerrar conexiones limpiamente.
      - En producción: draining de requests en curso (Graceful Shutdown).

    ¿Qué es Graceful Shutdown?
      Cuando el orquestador (Kubernetes, Docker) quiere detener el contenedor,
      envía SIGTERM. La app debe:
        1. Dejar de aceptar nuevas requests (Nginx la saca del pool).
        2. Terminar las requests en curso.
        3. Cerrar conexiones a DB, Redis, etc.
        4. Salir con código 0.
      Si no responde en X segundos → SIGKILL (muerte abrupta).
    """
    # ── STARTUP ──────────────────────────────────────────────────────────────
    setup_logging(
        log_level=settings.LOG_LEVEL,
        service_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )

    logger.info(
        "Iniciando aplicación",
        extra={
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )

    # Registrar info en Prometheus para que aparezca en Grafana
    app_info.info({
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    })

    # Verificar conexión con Redis
    redis_ok = await cache_service.ping()
    if not redis_ok:
        logger.warning("Redis no está disponible al arrancar. La app funcionará sin caché.")
    else:
        logger.info("Conexión con Redis establecida")

    logger.info(f"Aplicación lista en http://{settings.HOST}:{settings.PORT}")

    yield  # La app está corriendo y recibiendo requests aquí

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    logger.info("Cerrando aplicación (graceful shutdown)...")
    await cache_service.close()
    logger.info("Aplicación cerrada correctamente")


# ─── Aplicación FastAPI ───────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
    API de demo para la charla "Más allá del Localhost".

    Demuestra:
    - Health checks (liveness + readiness)
    - Caché con Redis (Cache-Aside pattern)
    - Rate limiting por IP
    - Métricas de Prometheus
    - Logging estructurado en JSON
    - Graceful shutdown
    """,
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc",    # ReDoc
    lifespan=lifespan,
)


# ─── Middleware ───────────────────────────────────────────────────────────────
# El orden importa: el middleware se aplica de abajo hacia arriba en los requests
# y de arriba hacia abajo en las respuestas.

# CORS: permite que un frontend en otro dominio llame a esta API.
# En producción: especifica los dominios exactos en allow_origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # En prod: ["https://tu-frontend.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next) -> Response:
    """
    Middleware que instrumenta CADA request con:
      - Métricas de Prometheus (latencia, status code, método).
      - Log JSON con contexto de la request.
      - Request ID único para correlacionar logs.

    Este middleware es el núcleo de la observabilidad de la app.
    Sin él, no tendrías visibilidad de qué está pasando en producción.
    """
    # Excluir /metrics y /health del tracking para no saturar las métricas
    skip_paths = {"/metrics", "/metrics/", "/health", "/ready"}
    path = request.url.path

    if path in skip_paths:
        return await call_next(request)

    # Request ID único — permite correlacionar el log de entrada con el de salida
    request_id = str(uuid.uuid4())[:8]

    start_time = time.perf_counter()
    http_active_requests.inc()

    logger.info(
        "Request recibida",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": path,
            "client_ip": request.client.host if request.client else "unknown",
        },
    )

    try:
        response = await call_next(request)
    except Exception as exc:
        # Error no manejado — responde 500 y lo registra
        http_requests_total.labels(
            method=request.method,
            path=path,
            status_code=500,
        ).inc()
        logger.error(
            "Error no manejado en request",
            extra={"request_id": request_id, "error": str(exc)},
        )
        raise
    finally:
        http_active_requests.dec()

    duration = time.perf_counter() - start_time

    # Registrar métricas en Prometheus
    http_requests_total.labels(
        method=request.method,
        path=path,
        status_code=response.status_code,
    ).inc()
    http_request_duration_seconds.labels(
        method=request.method,
        path=path,
    ).observe(duration)

    # Agregar request ID a la respuesta (útil para debugging del cliente)
    response.headers["X-Request-ID"] = request_id

    logger.info(
        "Request completada",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )

    return response


# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(items.router)


# ─── Prometheus /metrics ──────────────────────────────────────────────────────
# Monta la app de Prometheus como sub-aplicación ASGI en /metrics.
# Prometheus scrapeará este endpoint periódicamente (configurado en prometheus.yml).
# En producción podrías proteger este endpoint con autenticación básica.
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/", tags=["root"])
async def root() -> dict:
    """Endpoint raíz: confirma que la API está corriendo."""
    return {
        "message": f"Bienvenido a {settings.APP_NAME} v{settings.APP_VERSION}",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }
