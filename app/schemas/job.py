from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


JobState = Literal[
    "queued",
    "classifying",
    "extracting_digital",
    "chunking",
    "extracting_scans",
    "vision_rescue",
    "normalizing",
    "writing",
    "done",
    "error",
]


class JobRecord(BaseModel):
    job_id: str
    source_file: str
    status: JobState = "queued"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    page_count: int = 0
    pages_done: int = 0
    pages_total: int = 0
    current_chunk: str | None = None
    digital_pages: int = 0
    scanned_pages: int = 0
    vision_pages: int = 0
    message: str = ""
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
