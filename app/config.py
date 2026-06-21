"""
Configuración de la aplicación usando variables de entorno.

En producción NUNCA escribas secretos en el código.
Usa variables de entorno, un gestor de secretos (Vault, AWS Secrets Manager)
o archivos .env que NO se suban al repositorio.

pydantic-settings lee automáticamente desde el entorno o un archivo .env.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ─── Identidad del servicio ───────────────────────────────────────────────
    # APP_VERSION se define en el Dockerfile o docker-compose.yml.
    # Así podemos saber en qué versión está cada instancia durante un rolling update.
    APP_VERSION: str = "1.0.0"
    APP_NAME: str = "demo-api"

    # ─── Servidor ────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # ─── Redis ───────────────────────────────────────────────────────────────
    # La URL usa el nombre del servicio de docker-compose como hostname.
    # Docker resuelve "redis" al contenedor correcto automáticamente.
    REDIS_URL: str = "redis://redis:6379"
    CACHE_TTL_SECONDS: int = 60           # Tiempo de vida de las entradas en caché
    RATE_LIMIT_REQUESTS: int = 30         # Máximo de requests por ventana
    RATE_LIMIT_WINDOW_SECONDS: int = 60   # Duración de la ventana de rate limiting

    # ─── Entorno ─────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"      # development | staging | production

    model_config = SettingsConfigDict(
        env_file=".env",       # Carga desde .env si existe (útil en desarrollo local)
        case_sensitive=True,
    )


# Instancia global — se importa en toda la app.
# Se crea una sola vez al arrancar la aplicación.
settings = Settings()
