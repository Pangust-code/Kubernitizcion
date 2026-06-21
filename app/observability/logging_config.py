"""
Configuración de logging estructurado en formato JSON.

¿Por qué JSON?
- Los sistemas de log (Loki, CloudWatch, Datadog) lo indexan automáticamente.
- Puedes filtrar por campo: level="ERROR" AND service="demo-api"
- Incluye contexto de la request: request_id, user_id, trace_id, etc.

En desarrollo puedes usar logs legibles (texto plano).
En producción usa siempre JSON.

Ejemplo de log JSON generado:
{
  "timestamp": "2024-01-15T10:23:45.123Z",
  "level": "INFO",
  "service": "demo-api",
  "version": "1.0.0",
  "environment": "production",
  "message": "Request completada",
  "method": "GET",
  "path": "/items",
  "status_code": 200,
  "duration_ms": 12.3
}
"""

import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging(
    log_level: str = "INFO",
    service_name: str = "demo-api",
    version: str = "1.0.0",
    environment: str = "development",
) -> None:
    """
    Configura el logging global de la aplicación.

    Llama a esta función UNA vez al arrancar la app (en el lifespan de FastAPI).
    Todos los módulos que usen `logging.getLogger(__name__)` heredarán esta config.
    """

    # Formatter personalizado que añade campos fijos en cada log
    class ServiceJsonFormatter(jsonlogger.JsonFormatter):
        """Añade campos comunes a todos los logs."""

        def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
            super().add_fields(log_record, record, message_dict)
            # Timestamp ISO8601 explícito (el formatter base lo deja null a veces)
            from datetime import datetime, timezone
            log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
            # Campos que aparecen en TODOS los logs de este servicio
            log_record["service"] = service_name
            log_record["version"] = version
            log_record["environment"] = environment
            log_record["level"] = record.levelname

    # Handler: envía todos los logs a stdout
    # En Docker, stdout es capturado por el daemon y va a tu sistema de logging
    handler = logging.StreamHandler(sys.stdout)

    # En development: logs legibles. En producción: JSON puro.
    if environment == "development":
        # Formato legible para desarrollo
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    else:
        # JSON para producción — fácil de indexar con Loki, ELK, etc.
        handler.setFormatter(ServiceJsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s"
        ))

    # Configurar el root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Silenciar logs verbosos de librerías externas
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
