# ─── Dockerfile multi-stage ────────────────────────────────────────────────────
#
# ¿Por qué multi-stage?
#   Stage 1 (builder): instala dependencias (herramientas de build, compiladores).
#   Stage 2 (runtime): copia solo lo necesario para correr, sin el "ruido" del build.
#
# Resultado: imagen final mucho más pequeña (~200MB vs ~800MB) y más segura
# (menos superficie de ataque, sin herramientas de compilación).
#
# Comandos útiles:
#   docker build -t demo-api:1.0.0 .
#   docker build -t demo-api:2.0.0 --build-arg APP_VERSION=2.0.0 .
#   docker run -p 8000:8000 demo-api:1.0.0

# ─── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Instalar dependencias de sistema necesarias para compilar algunas librerías Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copiar requirements PRIMERO — esto maximiza el cache de Docker.
# Si requirements.txt no cambia, Docker reutiliza esta capa en el siguiente build.
# Solo si cambia requirements.txt se reinstala todo.
COPY requirements.txt .

# Instalar dependencias en un directorio local (sin contaminar el sistema)
# --no-cache-dir: no guarda el caché de pip (reduce tamaño de imagen)
# --prefix: instala en /build/deps para copiar al stage final
RUN pip install --no-cache-dir --prefix=/build/deps -r requirements.txt


# ─── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Argumento de build: permite cambiar la versión al hacer docker build.
# Ejemplo: docker build --build-arg APP_VERSION=2.0.0 .
# Esto es clave para la demo del rolling update: v1 y v2 tendrán distintas versiones.
ARG APP_VERSION=1.0.0

# Buenas prácticas de seguridad:
#   - No correr como root (principio de mínimo privilegio).
#   - Si hay una vulnerabilidad, el atacante tiene permisos limitados.
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --no-create-home appuser

WORKDIR /app

# Copiar las dependencias instaladas desde el builder
COPY --from=builder /build/deps /usr/local

# Copiar el código de la aplicación
# Hacemos esto DESPUÉS de copiar deps para aprovechar el cache de Docker:
# Si solo cambia el código (no los deps), el rebuild es muy rápido.
COPY --chown=appuser:appgroup ./app ./app

# Variables de entorno que definen el comportamiento de Python en contenedores:
#   PYTHONUNBUFFERED=1  → stdout/stderr sin buffer (los logs aparecen inmediatamente)
#   PYTHONDONTWRITEBYTECODE=1 → no genera archivos .pyc (ahorra espacio)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=${APP_VERSION} \
    PORT=8000

EXPOSE 8000

# Cambiar al usuario no-root
USER appuser

# Health check a nivel de Docker (diferente del health check de Nginx/Kubernetes).
# Docker reiniciará el contenedor si falla repetidamente.
# --interval: frecuencia de verificación
# --timeout:  tiempo máximo de espera por respuesta
# --retries:  intentos antes de marcar como unhealthy
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Arrancar uvicorn con configuración de producción.
# --workers 1: un worker por contenedor (escalar = más contenedores, no más workers).
# --loop uvloop: event loop más rápido que el default de asyncio.
# --log-level warning: uvicorn no hace logging de access (lo hace nuestra app).
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop", \
     "--log-level", "warning"]
