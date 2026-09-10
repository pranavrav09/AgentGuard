from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AGENTGUARD_",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "postgresql://agentguard:agentguard@localhost:5432/agentguard"
    opa_url: str = "http://localhost:8181"
    opa_timeout_seconds: float = Field(default=2.0, gt=0)
    lease_seconds: int = Field(default=30, ge=5, le=3600)
    poll_interval_seconds: float = Field(default=1.0, ge=0.05, le=60)
    max_job_attempts: int = Field(default=5, ge=1, le=50)
    worker_id: str = "secureguard-local"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
