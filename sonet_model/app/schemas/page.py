from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FormField(BaseModel):
    label: str
    value: str | None = None
    source: str = "sonnet"
    value_type: str | None = None


class Mark(BaseModel):
    label: str
    state: Literal["marked", "unmarked"]
    mark_type: str | None = None


class Signature(BaseModel):
    role: str = "unknown"
    state: Literal["present", "absent"] = "present"


class TableData(BaseModel):
    rows: list[list[str]] = Field(default_factory=list)


class PageExtraction(BaseModel):
    page: int
    route: str = "sonnet"
    document_type: str | None = None
    header: dict[str, str] = Field(default_factory=dict)
    fields: list[FormField] = Field(default_factory=list)
    marks: list[Mark] = Field(default_factory=list)
    circled_options: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    signatures: list[Signature] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    printed_text: str = ""
    handwritten_text: str = ""
    full_text: str = ""
    confidence: float | None = None
    needs_review: bool = False
    engine: str = ""
    warnings: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    job_id: str
    source_file: str
    page_count: int
    pages: list[PageExtraction] = Field(default_factory=list)
    digital_pages: int = 0
    scanned_pages: int = 0
    vision_pages: int = 0
    engines: list[str] = Field(default_factory=list)
