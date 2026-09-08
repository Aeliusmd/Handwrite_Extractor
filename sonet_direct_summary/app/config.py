"""Application settings loaded from .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    chunk_pages: int = 20
    max_chunk_pages: int = 100
    max_chunk_mb: int = 20
    max_parallel_chunks: int = 2
    max_output_tokens: int = 64000
    max_upload_mb: int = 500
    data_dir: str = "data/jobs"
    api_port: int = 8002

    mongodb_uri: str = "mongodb://10.103.0.201:27017/"
    mongodb_db: str = "handwritten_extractor"
    mongodb_collection: str = "extractions_sonnet_direct"
    mongodb_enabled: bool = True

    inline_extract: bool = False
    worker_poll_seconds: float = 2.0
    worker_max_jobs: int = 2
    worker_stale_minutes: int = 45
    sonnet_max_concurrent: int = 2
    summary_max_tokens: int = 16000

    @property
    def jobs_dir(self) -> Path:
        path = Path(self.data_dir)
        if not path.is_absolute():
            path = ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def credentials_ok(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.strip())

    @property
    def max_chunk_bytes(self) -> int:
        return max(1, self.max_chunk_mb) * 1024 * 1024

    def effective_chunk_pages(self) -> int:
        return max(1, min(self.chunk_pages, self.max_chunk_pages, 100))


@lru_cache
def get_settings() -> Settings:
    return Settings()
