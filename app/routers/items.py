"""
CRUD de items con caché Redis.

Patrón Cache-Aside (el más común en producción):
  1. GET /items/{id}:
     a. Buscar en Redis primero (hit → respuesta rápida, ~1ms).
     b. Si no está (miss) → calcular/buscar el dato real.
     c. Guardar el resultado en Redis para la próxima vez.

  2. PUT/DELETE /items/{id}:
     a. Actualizar/borrar el dato real.
     b. INVALIDAR el caché (muy importante — datos stale son peor que cache miss).

¿Por qué simular la "base de datos" en memoria?
  Para simplificar el demo. En producción usarías PostgreSQL, MongoDB, etc.
  La lógica de caché es idéntica.
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import settings
from app.services.cache import cache_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["items"])


# ─── Modelos ──────────────────────────────────────────────────────────────────
class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Nombre del item")
    description: str = Field("", max_length=500, description="Descripción opcional")
    price: float = Field(..., gt=0, description="Precio positivo")


class Item(ItemCreate):
    id: int
    created_at: str


# ─── "Base de datos" en memoria (solo para el demo) ──────────────────────────
# En un proyecto real esto sería SQLAlchemy, Motor (MongoDB), etc.
_fake_db: dict[int, dict[str, Any]] = {
    1: {"id": 1, "name": "Laptop Pro",    "description": "Laptop de alta gama",  "price": 1499.99, "created_at": "2024-01-01T00:00:00Z"},
    2: {"id": 2, "name": "Mouse Inalámbrico", "description": "Mouse ergonómico", "price": 29.99, "created_at": "2024-01-02T00:00:00Z"},
    3: {"id": 3, "name": "Teclado Mecánico",  "description": "Switches Cherry MX","price": 89.99, "created_at": "2024-01-03T00:00:00Z"},
}
_next_id: int = 4


def _cache_key(item_id: int) -> str:
    """Convención de nombrado de claves: '<namespace>:<id>'"""
    return f"items:{item_id}"

def _cache_key_list() -> str:
    return "items:list"


# ─── Dependency: Rate limiting ────────────────────────────────────────────────
async def check_rate_limit(request: Request) -> None:
    """
    Dependency de FastAPI que verifica el rate limit antes de cada request.

    Se inyecta con Depends() en cada endpoint que quieras proteger.
    Si la IP superó el límite → HTTPException 429 (Too Many Requests).

    En producción también considerarías:
      - Rate limit por API key / usuario autenticado
      - Rate limit diferenciado por plan (free vs premium)
      - Cabecera X-RateLimit-Remaining en la respuesta
    """
    # Obtener IP real: en producción viene del header X-Forwarded-For (Nginx lo agrega)
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    # Si hay múltiples proxies, la IP del cliente es la primera de la lista
    client_ip = client_ip.split(",")[0].strip()

    if await cache_service.is_rate_limited(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit excedido",
                "message": f"Máximo {settings.RATE_LIMIT_REQUESTS} requests por {settings.RATE_LIMIT_WINDOW_SECONDS}s",
                "retry_after": settings.RATE_LIMIT_WINDOW_SECONDS,
            },
        )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[Item])
async def list_items(_: None = Depends(check_rate_limit)) -> list[dict]:
    """
    Listar todos los items con caché.

    El caché de la lista se invalida cuando se crea o borra un item.
    TTL corto (10s) porque las listas cambian con más frecuencia.
    """
    cache_key = _cache_key_list()
    cached = await cache_service.get(cache_key, operation="list_items")
    if cached is not None:
        logger.info("Lista de items servida desde caché")
        return cached

    # Simular latencia de base de datos (en prod no haría esto)
    await asyncio.sleep(0.05)

    items = list(_fake_db.values())
    await cache_service.set(cache_key, items, ttl=10)  # Lista: TTL corto

    logger.info("Lista de items consultada desde 'DB'", extra={"count": len(items)})
    return items


@router.get("/{item_id}", response_model=Item)
async def get_item(item_id: int, _: None = Depends(check_rate_limit)) -> dict:
    """
    Obtener un item por ID con caché.

    Cache-Aside pattern:
      1. Buscar en Redis.
      2. Si miss → ir a la DB → guardar en Redis.
      3. Próximas requests: desde Redis (~1ms vs ~50ms de DB).
    """
    cache_key = _cache_key(item_id)
    cached = await cache_service.get(cache_key, operation="get_item")
    if cached is not None:
        logger.info("Item servido desde caché", extra={"item_id": item_id})
        return cached

    # Simular latencia de base de datos
    await asyncio.sleep(0.05)

    item = _fake_db.get(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} no encontrado",
        )

    # Guardar en caché para próximas requests
    await cache_service.set(cache_key, item, ttl=settings.CACHE_TTL_SECONDS)
    logger.info("Item consultado desde 'DB' y guardado en caché", extra={"item_id": item_id})
    return item


@router.post("/", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ItemCreate,
    _: None = Depends(check_rate_limit),
) -> dict:
    """Crear un nuevo item e invalidar el caché de la lista."""
    global _next_id
    from datetime import datetime, timezone

    new_item = {
        "id": _next_id,
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _fake_db[_next_id] = new_item
    _next_id += 1

    # Guardar en caché el item nuevo
    await cache_service.set(_cache_key(new_item["id"]), new_item, ttl=settings.CACHE_TTL_SECONDS)
    # Invalidar la lista: está desactualizada
    await cache_service.delete(_cache_key_list())

    logger.info("Item creado", extra={"item_id": new_item["id"], "name": new_item["name"]})
    return new_item


@router.put("/{item_id}", response_model=Item)
async def update_item(
    item_id: int,
    payload: ItemCreate,
    _: None = Depends(check_rate_limit),
) -> dict:
    """Actualizar un item e invalidar su caché."""
    if item_id not in _fake_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Item {item_id} no encontrado")

    _fake_db[item_id].update(payload.model_dump())
    updated = _fake_db[item_id]

    # Invalidar caché del item específico y de la lista
    await cache_service.delete(_cache_key(item_id))
    await cache_service.delete(_cache_key_list())

    logger.info("Item actualizado, caché invalidado", extra={"item_id": item_id})
    return updated


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, _: None = Depends(check_rate_limit)) -> None:
    """Borrar un item e invalidar caché."""
    if item_id not in _fake_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Item {item_id} no encontrado")

    del _fake_db[item_id]
    await cache_service.delete(_cache_key(item_id))
    await cache_service.delete(_cache_key_list())

    logger.info("Item borrado, caché invalidado", extra={"item_id": item_id})
