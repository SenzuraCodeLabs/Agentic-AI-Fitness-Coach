"""Central configuration.

Every secret and environment-dependent value enters the process here and only
here. Modules import ``settings`` rather than touching ``os.environ``, so there
is exactly one place to audit for secret handling, and a missing variable fails
at import time rather than at the first request that happens to need it.

``SecretStr`` is used for every credential because its ``repr`` is masked. A
stray ``log.info("config", cfg=settings)`` therefore cannot leak an API key,
which is a realistic failure mode in a structured-logging codebase.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---------------------------------------------------------------
    deepseek_api_key: SecretStr
    deepseek_base_url: str = "https://api.deepseek.com"
    # Model IDs are config, not constants: DeepSeek has renamed model IDs
    # before, and a rename should be a .env edit rather than a code change.
    deepseek_model_fast: str = "deepseek-v4-flash"
    deepseek_model_strong: str = "deepseek-v4-pro"
    llm_timeout_seconds: float = 20.0

    # --- Database ----------------------------------------------------------
    mongodb_uri: SecretStr
    mongodb_db: str = "fitcoach"

    # --- Email -------------------------------------------------------------
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""

    # --- Secrets -----------------------------------------------------------
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    agent_shared_secret: SecretStr

    # --- Vector store ------------------------------------------------------
    chroma_path: str = "./chroma_data"

    # --- Service discovery -------------------------------------------------
    gateway_url: str = "http://localhost:8000"
    agent1_url: str = "http://localhost:8001"
    agent2_url: str = "http://localhost:8002"
    agent3_url: str = "http://localhost:8003"

    # --- HTTP / security ---------------------------------------------------
    cors_origins: str = "http://localhost:3000"
    max_request_bytes: int = 32 * 1024
    max_message_chars: int = 4000

    # --- Rate limiting (L0) ------------------------------------------------
    rate_limit_user_per_minute: int = 20
    rate_limit_ip_per_minute: int = 60
    daily_token_quota: int = 100_000

    # --- Protocol ----------------------------------------------------------
    envelope_ttl_seconds: int = 120
    clock_skew_tolerance_seconds: int = 30

    # --- Runtime -----------------------------------------------------------
    environment: str = "development"
    log_level: str = "INFO"

    @field_validator("jwt_secret", "agent_shared_secret")
    @classmethod
    def _reject_placeholder_secrets(cls, v: SecretStr) -> SecretStr:
        """Refuse to start with a placeholder or trivially short secret.

        A short HMAC key weakens the envelope signature, and shipping the
        example value would mean every checkout of this repo shares a key.
        """
        raw = v.get_secret_value()
        if len(raw) < 16:
            raise ValueError("secret must be at least 16 characters")
        if raw.startswith("change-me"):
            raise ValueError("placeholder secret from .env.example is still in use")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so the ``.env`` file is parsed once. Tests clear the cache via
    ``get_settings.cache_clear()`` after monkeypatching the environment.
    """
    return Settings()  # type: ignore[call-arg]  # values come from env/.env


def describe_settings() -> dict[str, str]:
    """Non-secret settings, safe to log or expose on a health endpoint.

    Deliberately enumerates safe keys rather than dumping the model and
    filtering, so a newly added secret is excluded by default.
    """
    s = get_settings()
    return {
        "environment": s.environment,
        "mongodb_db": s.mongodb_db,
        "model_fast": s.deepseek_model_fast,
        "model_strong": s.deepseek_model_strong,
        "log_level": s.log_level,
    }
