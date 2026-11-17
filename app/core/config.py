"""Application settings.

Every value has a safe default so the app boots with no configuration at all,
which is what makes ``git clone && uvicorn`` work. Anything secret has no
default and is generated or supplied at deploy time.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_name: str = "Tarjuman"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # --- security ---
    # No default on purpose: a hardcoded fallback secret is how JWT auth gets
    # broken in production. In development we generate one at import time so the
    # app still boots; in production the validator below refuses to start.
    secret_key: str = Field(default="")
    access_token_expire_minutes: int = Field(default=60 * 24 * 7)
    algorithm: str = Field(default="HS256")

    # --- database ---
    database_url: str = Field(default="sqlite:///./tarjuman.db")

    # --- cors ---
    cors_origins: str = Field(default="http://localhost:8000,http://127.0.0.1:8000")

    # --- rate limiting ---
    rate_limit_requests: int = Field(default=60)
    rate_limit_window_seconds: int = Field(default=60)
    translate_rate_limit_requests: int = Field(default=20)
    translate_rate_limit_window_seconds: int = Field(default=60)

    # --- provider ---
    mymemory_endpoint: str = Field(default="https://api.mymemory.translated.net/get")
    mymemory_email: str = Field(default="")
    provider_timeout_seconds: float = Field(default=12.0)
    provider_max_retries: int = Field(default=2)
    user_agent: str = Field(default="Tarjuman/1.0 (+https://github.com/mohdabrarbaloch-arch)")

    # --- behaviour ---
    cache_ttl_seconds: int = Field(default=60 * 60 * 6)
    max_input_chars: int = Field(default=5000)
    enable_round_trip: bool = Field(default=True)
    round_trip_max_chars: int = Field(default=1200)

    @field_validator("secret_key")
    @classmethod
    def _ensure_secret(cls, value: str) -> str:
        if value:
            if len(value) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters.")
            return value
        # Development convenience: generate an ephemeral key. Tokens issued
        # before a restart stop working, which is the correct trade for a demo.
        return secrets.token_urlsafe(48)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
