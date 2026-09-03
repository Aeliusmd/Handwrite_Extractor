from __future__ import annotations

import json
import shutil
import uuid

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import get_settings
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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict:
    settings = get_settings()
    _validate_pdf(file.filename)
    if not settings.credentials_ok:
        raise HTTPException(
            status_code=500,
            detail=(
                "Google credentials are not configured. Set GCP_PROJECT_ID, "
                "DOCAI_PROCESSOR_ID, and GOOGLE_APPLICATION_CREDENTIALS in .env, "
                "and place the service-account JSON in credentials/."
            ),
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
        status="queued",
        message="Queued",
    )
    store.save(record)
    background_tasks.add_task(run_extraction, job_id)
    return {"job_id": job_id, "status": record.status}


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
    if record.status != "done" or not path.exists():
        raise HTTPException(status_code=409, detail="Extraction is not finished")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@router.get("/extract/{job_id}/txt")
def get_txt(job_id: str):
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = store.result_txt(job_id)
    if record.status != "done" or not path.exists():
        raise HTTPException(status_code=409, detail="Extraction is not finished")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename="extracted.txt",
    )


@router.post("/extract/{job_id}/retry")
def retry_job(job_id: str, background_tasks: BackgroundTasks) -> dict:
    record = store.load(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if record.status not in {"error", "done"}:
        raise HTTPException(status_code=409, detail="Job is still running")
    store.update(job_id, status="queued", error=None, message="Retry queued")
    background_tasks.add_task(run_extraction, job_id)
    return {"job_id": job_id, "status": "queued"}
