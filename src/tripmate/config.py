"""Application settings loaded from environment variables and .env."""

import os
from functools import lru_cache

import certifi
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    groq_api_key: str = Field(alias="GROQ_API_KEY")
    database_url: str = Field(alias="DATABASE_URL")

    # Live-data providers (agents fall back to non-live guidance without them)
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    aviation_stack_api_key: str = Field(
        default="",
        validation_alias="AVIATION_STACK_API_KEY",
    )
    openweather_api_key: str = Field(default="", alias="OPENWEATHER_API_KEY")

    # Server
    host: str = Field(default="127.0.0.1", alias="TRIPMATE_HOST")
    port: int = Field(default=8000, alias="TRIPMATE_PORT")
    log_level: str = Field(default="INFO", alias="TRIPMATE_LOG_LEVEL")

    # LLM
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        alias="TRIPMATE_GROQ_MODEL",
    )

    # Database pool
    db_pool_min_size: int = Field(default=1, alias="TRIPMATE_DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=5, alias="TRIPMATE_DB_POOL_MAX_SIZE")

    @property
    def database_dsn(self) -> str:
        """Connection string with sslmode=require appended when missing."""
        dsn = self.database_url
        if "sslmode=" not in dsn:
            separator = "&" if "?" in dsn else "?"
            dsn = f"{dsn}{separator}sslmode=require"
        return dsn


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_ssl_certificates() -> None:
    """Point outbound HTTPS clients at the certifi CA bundle.

    Required on some corporate/Conda Windows setups where the default
    certificate store is not picked up by requests/httpx subprocesses.
    """
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
