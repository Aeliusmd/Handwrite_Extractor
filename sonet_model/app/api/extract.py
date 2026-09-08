from __future__ import annotations

import json
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import get_settings
from app.db.queue import queue_stats
from app.pipeline.job_store import JobStore
from app.pipeline.runner import run_extraction
from app.schemas.job import JobRecord

router = APIRouter(prefix="/v1", tags=["extract"])
store = JobStore()


def _validate_pdf(filename: str | None) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file")


@router.post("/extract")
async def start_extract(
    file: UploadFile = File(...),
    user_id: str | None = Form(default=None),
) -> dict:
    settings = get_settings()
    _validate_pdf(file.filename)
    if not settings.credentials_ok:
        raise HTTPException(
            status_code=500,
            detail="Anthropic credentials are not configured. Set ANTHROPIC_API_KEY in sonet_model/.env",
        )

    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    dest = store.source_pdf(job_id)
    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    with dest.open("wb") as handle:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                dest.unlink(missing_ok=True)
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF exceeds {settings.max_upload_mb} MB",
                )
            handle.write(chunk)

    record = JobRecord(
        job_id=job_id,
        source_file=file.filename or "upload.pdf",
        user_id=(user_id.strip() if user_id else None),
        pdf_size_bytes=size,
        status="queued",
        message="Queued",
    )
    store.save(record)
    if settings.inline_extract:
        run_extraction(job_id)
        record = store.load(job_id) or record
        return {"job_id": job_id, "status": record.status, "user_id": record.user_id, "queued": False}
    return {
        "job_id": job_id,
        "status": record.status,
        "public_status": "unprocessed",
        "user_id": record.user_id,
        "queued": True,
    }


@router.get("/extract/{job_id}")
def get_job(job_id: str) -> JobRecord:
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return record


@router.get("/extract/{job_id}/json")
def get_json(job_id: str):
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = store.result_json(job_id)
    if not path.exists():
        raise HTTPException(status_code=409, detail="Extraction is not finished")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@router.get("/extract/{job_id}/txt")
def get_txt(job_id: str):
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = store.result_txt(job_id)
    if not path.exists():
        raise HTTPException(status_code=409, detail="Extraction is not finished")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename="extracted.txt",
    )


@router.get("/extract/{job_id}/summary")
def get_summary(job_id: str):
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = store.result_summary_txt(job_id)
    if not path.exists():
        raise HTTPException(status_code=409, detail="Summary is not finished")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename="summary.txt",
    )


@router.post("/extract/{job_id}/summarize")
def resummarize_job(job_id: str) -> dict:
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not store.result_txt(job_id).exists():
        raise HTTPException(status_code=409, detail="extracted.txt is not ready")
    from app.pipeline.summarize import run_summarization

    store.update(job_id, status="summarizing", message="Summarizing extracted.txt")
    try:
        path = run_summarization(store, job_id)
        store.update(job_id, status="done", message="Extraction and summary complete")
        return {"job_id": job_id, "status": "done", "summary_txt": str(path)}
    except Exception as exc:  # noqa: BLE001
        warnings = list(record.warnings) + [f"Summary failed: {exc}"]
        store.update(
            job_id,
            status="done",
            warnings=warnings,
            message=f"Extraction complete; summary failed: {exc}",
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/extract/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    settings = get_settings()
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if record.status not in {"error", "done"}:
        raise HTTPException(status_code=409, detail="Job is still running")
    store.update(job_id, status="queued", error=None, message="Retry queued")
    if settings.inline_extract:
        run_extraction(job_id)
    return {"job_id": job_id, "status": "queued", "queued": not settings.inline_extract}


@router.get("/queue/stats")
def get_queue_stats() -> dict:
    return queue_stats()
