"""Typed application settings, loaded from environment variables (12-factor style).

Secrets (API key, SMTP password, owner password, session secret) are only ever read
from the environment or a local, git-ignored ``.env`` file. They never live in code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Site -------------------------------------------------------------
    environment: str = Field("development", description="development | production | test")
    public_base_url: str = Field("http://localhost:8000", description="Public URL, e.g. https://example.com")
    site_name: str = "Open for Agents"
    database_path: Path = Path("data/app.db")
    seed_demo_data: bool = True

    # --- Security ---------------------------------------------------------
    secret_key: SecretStr = Field(SecretStr("dev-only-change-me"), description="Signs session cookies")
    owner_password: SecretStr = Field(SecretStr("dev-owner"), description="Password for the owner dashboard")
    session_max_age_seconds: int = 12 * 60 * 60
    rate_limit_per_minute: int = 20
    max_upload_bytes: int = 5 * 1024 * 1024
    use_system_truststore: bool = Field(
        False, description="Use the OS certificate store (needed behind TLS-inspecting corporate proxies)"
    )

    # --- Claude -----------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    extraction_model: str = "claude-sonnet-5-5"
    reply_model: str = "claude-haiku-5-5"
    shopper_model: str = "claude-sonnet-5-5"

    # --- Email (GoDaddy Titan mailbox) -----------------------------------
    smtp_host: str = "smtpout.secureserver.net"
    smtp_port: int = 465
    smtp_username: str | None = None  # full address, e.g. hello@yourdomain.com
    smtp_password: SecretStr | None = None
    mail_from: str | None = None  # defaults to smtp_username
    notify_email: str | None = None  # where enquiries / contact messages are delivered

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def public_host(self) -> str:
        return self.public_base_url.split("://", 1)[-1].split("/", 1)[0]

    @property
    def claude_enabled(self) -> bool:
        return self.anthropic_api_key is not None and bool(self.anthropic_api_key.get_secret_value())

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_username and self.smtp_password)

    @model_validator(mode="after")
    def _refuse_insecure_production_defaults(self) -> Settings:
        if self.environment == "production":
            weak = {"dev-only-change-me", "dev-owner"}
            if self.secret_key.get_secret_value() in weak or self.owner_password.get_secret_value() in weak:
                raise ValueError("SECRET_KEY and OWNER_PASSWORD must be set to strong values in production")
            if len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
