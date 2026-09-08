from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import ROOT
from app.db.mongo import ensure_indexes, ping, upsert_document
from app.schemas.job import JobRecord, JobState, to_public_status

if TYPE_CHECKING:
    from app.pipeline.job_store import JobStore

logger = logging.getLogger(__name__)


def _abs(path: Path) -> str:
    return str(path.resolve())


def _started_at(record: JobRecord, existing: dict | None) -> str | None:
    if record.status == "queued":
        return existing.get("timestamps", {}).get("started_at") if existing else None
    previous = existing.get("timestamps", {}).get("started_at") if existing else None
    return previous or datetime.now(timezone.utc).isoformat()


def _completed_at(record: JobRecord, existing: dict | None) -> str | None:
    if record.status == "done":
        previous = existing.get("timestamps", {}).get("completed_at") if existing else None
        return previous or datetime.now(timezone.utc).isoformat()
    if record.status == "error":
        previous = existing.get("timestamps", {}).get("completed_at") if existing else None
        return previous or datetime.now(timezone.utc).isoformat()
    return existing.get("timestamps", {}).get("completed_at") if existing else None


def _load_extraction_details(store: JobStore, job_id: str) -> dict | None:
    path = store.result_json(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Could not read extraction JSON for job %s", job_id)
        return None


def _txt_path_if_ready(store: JobStore, job_id: str, status: JobState) -> str | None:
    path = store.result_txt(job_id)
    if status == "done" and path.exists():
        return _abs(path)
    return None


def _json_path_if_ready(store: JobStore, job_id: str, status: JobState) -> str | None:
    path = store.result_json(job_id)
    if status == "done" and path.exists():
        return _abs(path)
    return None


def sync_job(store: JobStore, record: JobRecord) -> None:
    """Write/update the MongoDB extraction record. Never raises."""
    try:
        from app.db.mongo import get_collection

        collection = get_collection()
        existing = None
        if collection is not None:
            existing = collection.find_one(
                {"job_id": record.job_id},
                {"timestamps": 1, "files": 1, "claimed_by": 1, "claimed_at": 1},
            )

        details = None
        engines: list[str] = []
        if record.status == "done":
            details = _load_extraction_details(store, record.job_id)
            if details:
                engines = list(details.get("engines") or [])

        payload = {
            "job_id": record.job_id,
            "user_id": record.user_id,
            "status": to_public_status(record.status),
            "pipeline_status": record.status,
            "message": record.message,
            "error": record.error,
            "warnings": record.warnings,
            "pdf": {
                "original_filename": record.source_file,
                "stored_path": _abs(store.source_pdf(record.job_id)),
                "size_bytes": record.pdf_size_bytes,
                "content_type": "application/pdf",
                "page_count": record.page_count or record.pages_total,
                "digital_pages": record.digital_pages,
                "scanned_pages": record.scanned_pages,
            },
            "files": {
                "extracted_txt_path": _txt_path_if_ready(store, record.job_id, record.status),
                "extracted_json_path": _json_path_if_ready(store, record.job_id, record.status),
                "summary_pdf_path": (existing or {}).get("files", {}).get("summary_pdf_path"),
                "job_dir": _abs(store.job_dir(record.job_id)),
            },
            "extraction": {
                "pages_done": record.pages_done,
                "pages_total": record.pages_total,
                "vision_pages": record.vision_pages,
                "current_chunk": record.current_chunk,
                "engines": engines,
                "details": details,
            },
            "timestamps": {
                "created_at": record.created_at,
                "started_at": _started_at(record, existing),
                "completed_at": _completed_at(record, existing),
                "updated_at": record.updated_at,
            },
            "claimed_by": (existing or {}).get("claimed_by"),
            "claimed_at": (existing or {}).get("claimed_at"),
            "project_root": str(ROOT),
        }
        upsert_document(record.job_id, payload)
    except Exception:  # noqa: BLE001
        logger.exception("MongoDB sync skipped for job %s", record.job_id)


def startup_mongo() -> dict:
    ok = ping()
    if ok:
        try:
            ensure_indexes()
        except Exception:  # noqa: BLE001
            logger.exception("MongoDB index creation failed")
            ok = False
    return {"mongodb_connected": ok}
