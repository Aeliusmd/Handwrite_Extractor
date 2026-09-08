"""Application settings loaded from .env."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

_ENDPOINT_RE = re.compile(
    r"https://(?P<location>[a-z0-9-]+)-documentai\.googleapis\.com/"
    r"v\d+/projects/(?P<project>[^/]+)/locations/(?P<location2>[^/]+)"
    r"/processors/(?P<processor>[^/:]+)",
    re.IGNORECASE,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gcp_project_id: str = ""
    docai_location: str = "us"
    docai_processor_id: str = ""
    docai_prediction_endpoint: str = ""
    google_application_credentials: str = "./credentials/gcp-service-account.json"

    vertex_location: str = "us-central1"
    gemini_model: str = "gemini-2.5-flash"
    enable_vision_rescue: bool = True

    chunk_size: int = 15
    max_parallel_chunks: int = 4
    vision_max_pages: int = 40
    vision_dpi: int = 220
    digital_char_threshold: int = 80
    max_upload_mb: int = 500
    data_dir: str = "data/jobs"

    mongodb_uri: str = "mongodb://10.103.0.201:27017/"
    mongodb_db: str = "handwritten_extractor"
    mongodb_collection: str = "extractions"
    mongodb_enabled: bool = True

    inline_extract: bool = False
    worker_poll_seconds: float = 2.0
    worker_max_jobs: int = 2
    worker_stale_minutes: int = 45
    docai_max_concurrent: int = 8
    gemini_max_concurrent: int = 4

    def apply_prediction_endpoint(self) -> None:
        """Fill project/location/processor from the Document AI prediction URL if given."""
        raw = (self.docai_prediction_endpoint or "").strip()
        if not raw:
            return
        match = _ENDPOINT_RE.search(raw)
        if not match:
            raise ValueError(
                "DOCAI_PREDICTION_ENDPOINT is not a Document AI processor URL. "
                "Expected like https://us-documentai.googleapis.com/v1/projects/"
                "PROJECT/locations/us/processors/PROCESSOR_ID"
            )
        if not self.gcp_project_id:
            self.gcp_project_id = match.group("project")
        if not self.docai_processor_id:
            self.docai_processor_id = match.group("processor")
        self.docai_location = match.group("location2") or match.group("location")

    def apply_google_credentials(self) -> Path | None:
        raw = self.google_application_credentials.strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
            return path
        return path

    @property
    def jobs_dir(self) -> Path:
        path = Path(self.data_dir)
        if not path.is_absolute():
            path = ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def credentials_ok(self) -> bool:
        self.apply_prediction_endpoint()
        self.apply_google_credentials()
        return bool(self.gcp_project_id and self.docai_processor_id)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.apply_prediction_endpoint()
    settings.apply_google_credentials()
    return settings
