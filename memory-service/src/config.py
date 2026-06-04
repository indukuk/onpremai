from __future__ import annotations

from pydantic_settings import BaseSettings


class MemorySettings(BaseSettings):
    """Configuration for the memory service, loaded from environment variables."""

    # Database
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_NAME: str = "compliance_memory"
    DB_USER: str = "memory_svc"
    DB_PASSWORD: str = "password"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # LLM Gateway
    LLM_GATEWAY_URL: str = "http://llm-gateway:4000"

    # Embedding
    EMBEDDING_DIMENSION: int = 1024

    # Session
    SESSION_TTL_HOURS: int = 4
    SESSION_MAX_SIZE_BYTES: int = 262144  # 256KB

    # Interaction retention
    INTERACTION_RETENTION_DAYS: int = 90

    # Pattern decay
    PATTERN_DECAY_DAYS: int = 90
    PATTERN_DECAY_RATE: float = 0.1

    # Deduplication
    DEDUP_SIMILARITY_THRESHOLD: float = 0.9

    # Logging
    LOG_LEVEL: str = "info"

    # Server
    PORT: int = 5000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    model_config = {"env_prefix": "", "case_sensitive": True}


settings = MemorySettings()
