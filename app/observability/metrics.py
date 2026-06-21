"""
Métricas de Prometheus para la aplicación.

Prometheus trabaja con 4 tipos de métricas:
  - Counter:   Solo sube. Ejemplo: total de requests.
  - Gauge:     Sube y baja. Ejemplo: requests activas en este momento.
  - Histogram: Distribución de valores. Ejemplo: latencia de requests.
  - Summary:   Similar al histogram pero calcula percentiles en el cliente.

En producción exportas estas métricas en /metrics y Prometheus las
"scrapea" (recolecta) periódicamente. Grafana las visualiza.
"""

from prometheus_client import Counter, Histogram, Gauge, Info

# ─── Información del servicio ────────────────────────────────────────────────
# Info es un tipo especial que expone labels de texto.
# Útil para saber qué versión está corriendo en cada instancia.
app_info = Info(
    "app",
    "Información sobre la instancia de la aplicación",
)

# ─── HTTP Request Metrics ─────────────────────────────────────────────────────
# Cada request incrementa este counter con su método, path y status code.
# En Grafana puedes calcular: rate(http_requests_total[1m]) → requests por segundo
http_requests_total = Counter(
    name="http_requests_total",
    documentation="Total de HTTP requests recibidas",
    labelnames=["method", "path", "status_code"],
)

# Histogram para medir latencia.
# Los "buckets" definen los intervalos que Prometheus almacena.
# Ejemplo: cuántas requests tardaron menos de 50ms, menos de 100ms, etc.
http_request_duration_seconds = Histogram(
    name="http_request_duration_seconds",
    documentation="Duración de HTTP requests en segundos",
    labelnames=["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# Gauge para requests activas en este instante.
# Sube cuando llega una request, baja cuando termina.
# Un valor muy alto puede indicar que el servidor está saturado.
http_active_requests = Gauge(
    name="http_active_requests",
    documentation="Número de HTTP requests siendo procesadas en este momento",
)

# ─── Cache Metrics ────────────────────────────────────────────────────────────
# Hit: el dato estaba en caché (rápido, sin ir a la DB).
# Miss: el dato NO estaba en caché (más lento, fue a la DB/Redis).
# Cache hit rate = hits / (hits + misses). En prod queremos > 80%.
cache_hits_total = Counter(
    name="cache_hits_total",
    documentation="Número de veces que se encontró el dato en caché",
    labelnames=["operation"],
)

cache_misses_total = Counter(
    name="cache_misses_total",
    documentation="Número de veces que NO se encontró el dato en caché",
    labelnames=["operation"],
)

# ─── Rate Limiting Metrics ────────────────────────────────────────────────────
# Cuántas veces rechazamos requests por exceder el rate limit.
# Si este número sube rápido, puede haber un ataque o un cliente buggy.
rate_limit_hits_total = Counter(
    name="rate_limit_hits_total",
    documentation="Requests rechazadas por rate limiting",
    labelnames=["client_ip"],
)
