"""Environment-driven application settings."""
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/app.db"

    graph_backend: Literal["memory", "neo4j"] = "memory"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""

    document_storage_dir: str = "./data/documents"
    document_processor_mode: Literal["local", "local_ocr"] = "local"
    max_upload_mb: int = Field(default=20, ge=1)
    classification_review_threshold: float = Field(default=0.6, ge=0, le=1)
    auto_migrate: bool = True
    materiality_threshold_pct: Decimal = Decimal("5")
    reconciliation_policy_path: str = ""
    reconciliation_as_of_date: date | None = None

    use_mock_bedrock: bool = True
    aws_region: str = ""
    bedrock_model_id: str = ""
    llm_timeout_seconds: int = Field(default=60, ge=1)
    llm_max_retries: int = Field(default=3, ge=0, le=8)
    llm_max_tokens: int = Field(default=4096, ge=256)
    extraction_confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    embeddings_mode: Literal["placeholder"] = "placeholder"
    bedrock_embedding_model_id: str = ""

    cors_origins: str = "http://localhost:5173"

    @field_validator("reconciliation_as_of_date", mode="before")
    @classmethod
    def _blank_date_is_none(cls, value):
        return None if value in ("", None) else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
