"""Configuration settings for FixLoop backend.

Loads environment variables with secure defaults and prevents leaking secrets.
"""

from typing import List, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Nebius Token Factory / AI Studio
    NEBIUS_API_KEY: Optional[SecretStr] = Field(default=None, description="Nebius Token Factory API Key")
    NEBIUS_BASE_URL: str = Field(default="https://api.tokenfactory.nebius.com/v1", description="Base URL for Nebius API")
    NEBIUS_MODEL: str = Field(default="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", description="Target NVIDIA model ID")

    # Offline / Test Fallback
    USE_MOCK_LLM: bool = Field(default=False, description="When true, use deterministic mock LLM provider")

    # Server Configuration
    FIXLOOP_HOST: str = Field(default="127.0.0.1")
    FIXLOOP_PORT: int = Field(default=8000)
    DEBUG_MODE: bool = Field(default=False)
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    # HTTPX & LLM Client Configuration
    HTTPX_CONNECT_TIMEOUT: float = Field(default=10.0, description="HTTP connection timeout in seconds")
    HTTPX_READ_TIMEOUT: float = Field(default=45.0, description="HTTP read timeout in seconds")
    HTTPX_WRITE_TIMEOUT: float = Field(default=10.0, description="HTTP write timeout in seconds")
    HTTPX_MAX_RETRIES: int = Field(default=2, description="Max retry attempts for transient server errors")

    # Sandbox / Diagnostic Limits
    DOCKER_HOST_OVERRIDE: Optional[str] = None
    DOCKER_COMMAND_TIMEOUT_SECONDS: int = Field(default=30)
    MAX_DIAGNOSTIC_ITERATIONS: int = Field(default=5)
    REQUIRE_APPROVAL_FOR_CONTAINER_RESTART: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_nebius_configured(self) -> bool:
        return bool(self.NEBIUS_API_KEY and self.NEBIUS_API_KEY.get_secret_value().strip())

    def get_nebius_api_key(self) -> Optional[str]:
        if self.NEBIUS_API_KEY:
            val = self.NEBIUS_API_KEY.get_secret_value().strip()
            return val if val else None
        return None

    @property
    def normalized_nebius_base_url(self) -> str:
        return self.NEBIUS_BASE_URL.rstrip("/")


settings = Settings()
