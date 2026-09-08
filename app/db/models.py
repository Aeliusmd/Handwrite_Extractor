from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PdfDetails(BaseModel):
    original_filename: str = ""
    stored_path: str | None = None
    size_bytes: int = 0
    content_type: str = "application/pdf"
    page_count: int = 0
    digital_pages: int = 0
    scanned_pages: int = 0


class OutputFiles(BaseModel):
    extracted_txt_path: str | None = None
    extracted_json_path: str | None = None
    summary_pdf_path: str | None = None
    job_dir: str | None = None


class ExtractionProgress(BaseModel):
    pages_done: int = 0
    pages_total: int = 0
    vision_pages: int = 0
    current_chunk: str | None = None
    engines: list[str] = Field(default_factory=list)
    details: dict[str, Any] | None = None


class ExtractionTimestamps(BaseModel):
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None
