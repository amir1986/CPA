"""Application settings, loaded from environment variables via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ollama Cloud ──
    ollama_api_keys: str = Field(
        default="",
        description="Newline- or comma-separated Ollama Cloud API keys.",
    )
    ollama_api_keys_file: Path | None = Field(
        default=None,
        description="Optional path to a file containing keys (one per line). Takes precedence over OLLAMA_API_KEYS if set.",
    )
    ollama_base_url: str = "https://ollama.com"
    ollama_model: str = "gpt-oss:120b"
    ollama_rate_limit_cooldown_seconds: float = 60.0
    ollama_max_retries_per_key: int = 2
    ollama_request_timeout_seconds: float = 120.0

    # ── Database ──
    database_url: str = "postgresql+asyncpg://cpa:cpa@postgres:5432/cpa"

    # ── Qdrant ──
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: SecretStr | None = None

    # ── Object storage ──
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: SecretStr = SecretStr("cpa")
    s3_secret_key: SecretStr = SecretStr("cpa-secret")
    s3_bucket: str = "cpa"
    s3_region: str = "us-east-1"

    # ── Embeddings ──
    embed_model: str = "intfloat/multilingual-e5-large"
    embed_device: str = "cpu"

    # ── Auth ──
    jwt_secret: SecretStr = SecretStr("dev-jwt-secret-change-me-please-32b")
    jwt_access_ttl_seconds: int = 1800
    jwt_refresh_ttl_seconds: int = 2592000
    admin_api_key: SecretStr = SecretStr("dev-admin-key")

    # ── SMTP ──
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "cpa@example.com"
    smtp_starttls: bool = False

    # ── Retrieval ──
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.25
    retrieval_lang_strict_he: bool = True

    # ── Telemetry / logging ──
    otel_exporter_otlp_endpoint: str | None = None
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        return v.upper()

    def resolved_api_keys(self) -> list[str]:
        """Return the list of Ollama API keys, dedup'd and in declared order.

        Source precedence: `OLLAMA_API_KEYS_FILE` if set and readable; else `OLLAMA_API_KEYS`.
        Accepts newline- or comma-separated values. Whitespace is stripped; empty lines ignored.
        """
        raw: str
        if self.ollama_api_keys_file and self.ollama_api_keys_file.exists():
            raw = self.ollama_api_keys_file.read_text(encoding="utf-8")
        else:
            raw = self.ollama_api_keys

        seen: set[str] = set()
        out: list[str] = []
        for chunk in raw.replace(",", "\n").splitlines():
            key = chunk.strip()
            if key and key not in seen:
                seen.add(key)
                out.append(key)
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
