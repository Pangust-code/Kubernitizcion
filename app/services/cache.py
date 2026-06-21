"""
Servicio de caché usando Redis.

Redis se usa aquí para dos propósitos:
  1. CACHÉ: guardar respuestas costosas para no recalcularlas.
  2. RATE LIMITING: contar requests por IP en una ventana de tiempo.

¿Por qué Redis y no memoria local?
  Porque tenemos MÚLTIPLES instancias de la API (escalado horizontal).
  Si guardáramos el caché en memoria de cada proceso, cada instancia
  tendría su propio caché desincronizado. Redis es el estado compartido.

Diagrama:
  instancia 1 ──┐
  instancia 2 ──┤──► Redis (caché compartido)
  instancia N ──┘
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.observability.metrics import (
    cache_hits_total,
    cache_misses_total,
    rate_limit_hits_total,
)

logger = logging.getLogger(__name__)


class CacheService:
    """
    Wrapper sobre Redis con soporte de caché + rate limiting.

    Usamos el cliente asíncrono (redis.asyncio) porque FastAPI es async.
    Si usaras el cliente síncrono bloquearías el event loop.
    """

    def __init__(self, redis_url: str) -> None:
        # decode_responses=True: Redis devuelve strings en vez de bytes
        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,   # Tiempo máximo para conectar
            socket_timeout=3,           # Tiempo máximo para operaciones
        )

    async def get(self, key: str, operation: str = "get") -> Any | None:
        """
        Lee un valor del caché.

        Returns:
            El valor deserializado, o None si no existe.
        """
        try:
            raw = await self._redis.get(key)
            if raw is None:
                # Cache MISS: el dato no está, hay que calcularlo
                cache_misses_total.labels(operation=operation).inc()
                return None

            # Cache HIT: devolvemos el dato sin ir a la fuente original
            cache_hits_total.labels(operation=operation).inc()
            return json.loads(raw)

        except Exception as e:
            # Si Redis falla, logueamos pero no crasheamos la app.
            # La app degrada graciosamente: funciona sin caché.
            logger.warning("Redis GET falló, continuando sin caché", extra={"key": key, "error": str(e)})
            cache_misses_total.labels(operation=operation).inc()
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Guarda un valor en el caché.

        Args:
            key:   Clave única. Usa namespaces: "items:123", "user:456"
            value: Cualquier valor serializable a JSON.
            ttl:   Time-to-live en segundos. None = sin expiración (cuidado en prod)
        """
        try:
            serialized = json.dumps(value)
            if ttl:
                # EX = expire in X seconds
                await self._redis.set(key, serialized, ex=ttl)
            else:
                await self._redis.set(key, serialized)
        except Exception as e:
            # Fallo silencioso: si no podemos guardar en caché, no importa.
            # El dato llegó correctamente al cliente igualmente.
            logger.warning("Redis SET falló", extra={"key": key, "error": str(e)})

    async def delete(self, key: str) -> None:
        """Invalida una entrada del caché. Llamar al actualizar/borrar datos."""
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.warning("Redis DELETE falló", extra={"key": key, "error": str(e)})

    async def delete_pattern(self, pattern: str) -> int:
        """
        Borra todas las claves que coincidan con un patrón.

        Ejemplo: delete_pattern("items:*") borra todos los items del caché.
        CUIDADO: SCAN es O(N) en bases grandes. Úsalo con precaución en prod.
        """
        try:
            keys = await self._redis.keys(pattern)
            if keys:
                await self._redis.delete(*keys)
            return len(keys)
        except Exception as e:
            logger.warning("Redis DELETE_PATTERN falló", extra={"pattern": pattern, "error": str(e)})
            return 0

    async def is_rate_limited(self, client_ip: str) -> bool:
        """
        Implementa rate limiting con el patrón "sliding window counter".

        Cómo funciona:
          1. Cada IP tiene una clave en Redis con un contador.
          2. El contador se incrementa con cada request.
          3. Si supera el límite, rechazamos la request.
          4. La clave expira automáticamente después de la ventana de tiempo.

        Ejemplo: máx 30 requests por minuto por IP.
        """
        key = f"rate_limit:{client_ip}"
        try:
            # Pipeline: ejecuta múltiples comandos en una sola round-trip a Redis
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)                                           # Incrementar contador
                pipe.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS)    # Resetear TTL
                results = await pipe.execute()

            current_count = results[0]

            if current_count > settings.RATE_LIMIT_REQUESTS:
                # Registramos el hit para verlo en Grafana
                rate_limit_hits_total.labels(client_ip=client_ip).inc()
                logger.warning(
                    "Rate limit excedido",
                    extra={"client_ip": client_ip, "count": current_count, "limit": settings.RATE_LIMIT_REQUESTS},
                )
                return True

            return False

        except Exception as e:
            # Si Redis falla, permitimos la request (fail-open).
            # En sistemas de alta seguridad podrías hacer fail-closed.
            logger.error("Error verificando rate limit, permitiendo request", extra={"error": str(e)})
            return False

    async def ping(self) -> bool:
        """Verifica que la conexión con Redis funciona. Usado en health checks."""
        try:
            return await self._redis.ping()
        except Exception:
            return False

    async def close(self) -> None:
        """Cierra la conexión al hacer shutdown de la app."""
        await self._redis.aclose()


# ─── Instancia global ─────────────────────────────────────────────────────────
# Se crea una vez al arrancar y se cierra limpiamente al apagar (lifespan).
cache_service = CacheService(settings.REDIS_URL)
