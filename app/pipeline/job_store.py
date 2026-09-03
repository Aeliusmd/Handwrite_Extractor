from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.schemas.job import JobRecord, JobState


class JobStore:
    def __init__(self, jobs_dir: Path | None = None) -> None:
        self.jobs_dir = jobs_dir or get_settings().jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        path = self.jobs_dir / job_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "pages").mkdir(exist_ok=True)
        (path / "chunks").mkdir(exist_ok=True)
        (path / "chunk_pdfs").mkdir(exist_ok=True)
        (path / "vision").mkdir(exist_ok=True)
        return path

    def source_pdf(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "source.pdf"

    def record_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def result_json(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "extracted.json"

    def result_txt(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "extracted.txt"

    def page_path(self, job_id: str, page: int) -> Path:
        return self.job_dir(job_id) / "pages" / f"{page:04d}.json"

    def chunk_result_path(self, job_id: str, start: int, end: int) -> Path:
        return self.job_dir(job_id) / "chunks" / f"{start:04d}_{end:04d}.json"

    def save(self, record: JobRecord) -> None:
        record.touch()
        path = self.record_path(record.job_id)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def load(self, job_id: str) -> JobRecord | None:
        path = self.record_path(job_id)
        if not path.exists():
            return None
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def update(
        self,
        job_id: str,
        *,
        status: JobState | None = None,
        message: str | None = None,
        **kwargs,
    ) -> JobRecord:
        record = self.load(job_id)
        if record is None:
            raise FileNotFoundError(f"Unknown job {job_id}")
        if status is not None:
            record.status = status
        if message is not None:
            record.message = message
        for key, value in kwargs.items():
            setattr(record, key, value)
        self.save(record)
        return record

    def save_page(self, job_id: str, payload: dict) -> None:
        page = int(payload["page"])
        path = self.page_path(job_id, page)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_pages(self, job_id: str) -> list[dict]:
        folder = self.job_dir(job_id) / "pages"
        pages = []
        for path in sorted(folder.glob("*.json")):
            pages.append(json.loads(path.read_text(encoding="utf-8")))
        pages.sort(key=lambda item: item["page"])
        return pages

    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
