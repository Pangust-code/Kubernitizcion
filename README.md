# Más allá del Localhost
### Demo: Estrategias de lanzamiento a producción

Aplicación de ejemplo para la charla. Demuestra en la práctica los conceptos de disponibilidad, balanceo de carga, caché, rate limiting, observabilidad y despliegue sin downtime.

---

## Arquitectura

```
Cliente
  │
  ▼ :80
┌─────────────────────────────────────────┐
│           Nginx (Load Balancer)          │
│    Round-robin · health checks · rate   │
└─────────────┬───────────────┬───────────┘
              │               │
         ┌────▼────┐     ┌────▼────┐
         │  api1   │     │  api2   │
         │  :8000  │     │  :8000  │
         │ FastAPI │     │ FastAPI │
         └────┬────┘     └────┬────┘
              └───────┬───────┘
                      ▼
                ┌───────────┐
                │   Redis   │  ← Caché compartido + Rate limiting
                │   :6379   │
                └───────────┘

Observabilidad:
  api1, api2 ──► /metrics ──► Prometheus :9090 ──► Grafana :3000
  redis       ──► redis-exporter :9121
  nginx       ──► nginx-exporter :9113 (vía /stub_status)
```

> El diagrama completo está en [`arquitectura.svg`](arquitectura.svg).

## Stack

| Componente | Tecnología | Propósito |
|---|---|---|
| API | FastAPI (Python 3.12) | Lógica de negocio |
| Cache / Rate Limit | Redis 7 | Estado compartido entre instancias |
| Load Balancer | Nginx 1.27 | Distribuir tráfico + reverse proxy |
| Métricas | Prometheus | Recolección de métricas |
| Dashboard | Grafana | Visualización |
| Exporters | redis-exporter, nginx-exporter | Métricas de infraestructura |

---

## Requisitos

- Docker >= 24.0
- Docker Compose >= 2.20
- ~2 GB RAM disponible

---

## Inicio rápido

```bash
# 1. Clonar el repositorio
git clone https://github.com/ctimbi/mas-alla-del-localhost.git
cd mas-alla-del-localhost

# 2. Copiar variables de entorno
cp .env.example .env

# 3. Levantar todo el stack (SIEMPRE usar docker compose up -d completo la primera vez)
docker compose up --build -d

# 4. Verificar estado — esperar que todos estén "running (healthy)"
docker compose ps
```

**Salida esperada** una vez todo esté listo:

```
NAME                  SERVICE           STATUS               PORTS
demo-api1             api1              running (healthy)    8000/tcp
demo-api2             api2              running (healthy)    8000/tcp
demo-grafana          grafana           running (healthy)    0.0.0.0:3000->3000/tcp
demo-nginx-exporter   nginx-exporter    running
demo-prometheus       prometheus        running (healthy)    0.0.0.0:9090->9090/tcp
demo-redis            redis             running (healthy)    6379/tcp
demo-redis-exporter   redis-exporter    running              9121/tcp
demo_nginx_1          nginx             running (healthy)    0.0.0.0:80->80/tcp
```

> **Nota sobre hostnames:** Docker asigna un hash aleatorio como hostname a cada contenedor (ej: `9cc498e998d6`). Al llamar a `/info` verás ese hash, no `demo-api1`. Eso es el comportamiento correcto — cada instancia tiene su propio identificador único.

Una vez levantado:

| URL | Descripción |
|---|---|
| http://localhost | API (vía Nginx) |
| http://localhost/docs | Swagger UI |
| http://localhost/health | Liveness probe |
| http://localhost/ready | Readiness probe |
| http://localhost/info | Versión, hostname e instancia |
| http://localhost/metrics | Métricas en formato Prometheus |
| http://localhost:9090 | Prometheus UI |
| http://localhost:3000 | Grafana (admin / admin123) |

---

## Verificación rápida

```bash
# Health check
curl http://localhost/health
# {"status":"ok","timestamp":"2026-06-08T15:18:17.834082+00:00","uptime_seconds":155.18}

# Info de la instancia que respondió
curl http://localhost/info
# {"app":"demo-api","version":"1.0.0","hostname":"9cc498e998d6",...}

# Listar items
curl http://localhost/items/
# [{"name":"Laptop Pro",...},{"name":"Mouse Inalámbrico",...},...]

# Ver el balanceo de carga — hostname alterna en cada request
for i in $(seq 1 6); do
  curl -s http://localhost/info | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(f'  {d[\"hostname\"]}  v{d[\"version\"]}')"
done
# Salida real:
#   9cc498e998d6  v1.0.0    ← api1
#   b2aa7571cfb1  v1.0.0    ← api2
#   9cc498e998d6  v1.0.0    ← api1
#   b2aa7571cfb1  v1.0.0    ← api2
#   ...
```

---

## Script de demo interactivo

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

| Opción | Concepto |
|---|---|
| 1 | Estado del stack |
| 2 | Health checks (liveness + readiness) |
| 3 | Balanceo de carga — ver qué instancia responde |
| 4 | Caché Redis — cache hit vs miss con `time` |
| 5 | Rate limiting — HTTP 429 a partir de la request 31 |
| 6 | Métricas — generar tráfico y ver en Grafana |
| **7** | **Rolling update sin downtime** ← la demo principal |
| 8 | Fallo y recuperación automática |

---

## Demo del Rolling Update

Esta es la demo central de la charla. Actualizar la app sin que los usuarios noten nada.

**Terminal 1 — monitoreo continuo:**
```bash
while true; do
  curl -s http://localhost/info | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(f'  {d[\"hostname\"]}  v{d[\"version\"]}')"
  sleep 0.5
done
```

**Terminal 2 — ejecutar el update:**
```bash
# Construir imagen v2.0.0 y actualizar api1
docker compose build --build-arg APP_VERSION=2.0.0 api1
docker compose up -d --no-deps api1
```

**Salida real en Terminal 1** durante el update:
```
  9cc498e998d6  v1.0.0    ← ambas en v1
  b2aa7571cfb1  v1.0.0
  b2aa7571cfb1  v1.0.0    ← api1 reiniciando, solo responde api2
  b2aa7571cfb1  v1.0.0    ← sin errores para el cliente
  9cc498e998d6  v2.0.0    ← api1 lista, vuelve al pool con v2
  b2aa7571cfb1  v1.0.0    ← api2 sigue en v1 (coexistencia normal)
  9cc498e998d6  v2.0.0
```

**Luego actualizar api2:**
```bash
docker compose build --build-arg APP_VERSION=2.0.0 api2
docker compose up -d --no-deps api2
```

**Rollback** — si v2 tiene un bug:
```bash
# Volver a la imagen v1.0.0
docker compose build --build-arg APP_VERSION=1.0.0 api1
docker compose up -d --no-deps api1
# Nginx detecta el health check en segundos y redirige el tráfico automáticamente
```

> **Importante — precedencia de variables de entorno en Docker:**
> Si defines `APP_VERSION` en la sección `environment:` de docker-compose, **ese valor gana siempre**, sin importar el `--build-arg`. Por eso en este proyecto `APP_VERSION` no está en `environment:` — se bake en la imagen vía `ARG` → `ENV` en el Dockerfile y Docker Compose no lo sobreescribe.
>
> Precedencia (de mayor a menor): `environment:` en compose → `ENV` en Dockerfile → `--build-arg`

> **Sobre `--no-deps`:** solo funciona si el stack ya está corriendo. Para la primera vez, siempre usar `docker compose up -d` completo.

---

## Estructura del proyecto

```
.
├── app/
│   ├── main.py                    # FastAPI app + middleware + lifespan
│   ├── config.py                  # Configuración desde variables de entorno
│   ├── routers/
│   │   ├── health.py              # /health, /ready, /info
│   │   └── items.py               # CRUD con caché Redis + rate limiting
│   ├── services/
│   │   └── cache.py               # CacheService: caché + rate limiting con Redis
│   └── observability/
│       ├── metrics.py             # Definición de métricas Prometheus
│       └── logging_config.py      # Logging estructurado JSON
├── nginx/
│   └── nginx.conf                 # Load balancer + /stub_status para nginx-exporter
├── prometheus/
│   └── prometheus.yml             # Configuración de scraping
├── grafana/
│   ├── provisioning/              # Config automática de Grafana al arrancar
│   └── dashboards/                # Dashboards pre-configurados
├── scripts/
│   └── demo.sh                    # Script de demo interactivo (8 opciones)
├── arquitectura.svg               # Diagrama de arquitectura
├── GUIA_DOCENTE.md                # Guía pedagógica para el instructor
├── Dockerfile                     # Multi-stage build (builder + runtime)
├── docker-compose.yml             # Orquestación completa (8 servicios)
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Conceptos demostrados

### Health Checks
- `/health` → **Liveness**: el proceso está vivo. Rápido, sin verificar dependencias.
- `/ready` → **Readiness**: verifica Redis. Si falla → HTTP 503 y Nginx lo saca del pool.
- Demo: `docker compose stop redis` → `/ready` devuelve 503. `docker compose start redis` → vuelve a 200.

### Caché (Cache-Aside Pattern)
- GET: buscar en Redis → si miss, ir a la "DB" → guardar en Redis con TTL.
- PUT/DELETE: actualizar dato + invalidar caché inmediatamente.
- Ver claves en vivo: `docker exec demo-redis redis-cli KEYS '*'`

### Rate Limiting (dos capas)
- **Nginx**: 10 req/s por IP (primera línea, antes de llegar a la app).
- **Aplicación**: 30 req/min por IP usando Redis como contador compartido.
- Sin Redis compartido, el límite efectivo sería `30 × N_instancias`.

### Observabilidad
- **Logs JSON**: cada request tiene `request_id`, `duration_ms`, `status_code`, `timestamp`.
- **Métricas**: `http_requests_total`, `http_request_duration_seconds`, `cache_hits_total`, `rate_limit_hits_total`.
- **Grafana**: dashboard pre-configurado en http://localhost:3000.

### Graceful Shutdown
Al recibir SIGTERM: termina requests en curso → cierra conexión Redis → sale con código 0.
Configurado en el `lifespan` de FastAPI.

---

## Troubleshooting

| Síntoma | Causa | Solución |
|---|---|---|
| Contenedores en estado `created` | Se usó `--no-deps` sin que el stack estuviera corriendo | `docker compose up -d` completo |
| `nginx-exporter` error `failed to parse` | El exporter apuntaba a `/nginx-health` en vez de `/stub_status` | Ya corregido en `nginx.conf` |
| `timestamp: null` en los logs | pythonjsonlogger no resuelve `%(timestamp)s` automáticamente | Ya corregido en `logging_config.py` |
| `/metrics/` genera spam en logs | Prometheus scrapea cada 10s y pasaba por el middleware | Ya excluido del middleware en `main.py` |
| Rolling update muestra siempre `v1.0.0` | `APP_VERSION=1.0.0` en `environment:` sobreescribía el `--build-arg` | Removido de `environment:` en `docker-compose.yml` |
| `curl: Failed to connect to localhost port 80` | Nginx no ha terminado de arrancar o Redis no está healthy | Esperar 20s y ejecutar `docker compose up -d` |

---

## Próximos pasos

- [ ] Agregar PostgreSQL + SQLAlchemy async
- [ ] Implementar trazas distribuidas con OpenTelemetry + Jaeger
- [ ] Agregar autenticación JWT
- [ ] Configurar alertas en Grafana (error rate > 5% por 2 minutos)
- [ ] Desplegar en Kubernetes (`kompose convert` como punto de partida)
- [ ] Agregar CI/CD con GitHub Actions

---

## Recursos

- [FastAPI Docs](https://fastapi.tiangolo.com)
- [Prometheus Docs](https://prometheus.io/docs)
- [Site Reliability Engineering — Google](https://sre.google/books/)
- [The Twelve-Factor App](https://12factor.net)
- [Redis Patterns](https://redis.io/docs/manual/patterns/)
#   K u b e r n i t i z c i o n  
 