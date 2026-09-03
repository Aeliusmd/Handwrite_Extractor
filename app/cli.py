"""CLI: python -m app.cli path/to/file.pdf"""

from __future__ import annotations

import argparse
import shutil
import uuid
from pathlib import Path

from app.config import get_settings
from app.pipeline.job_store import JobStore
from app.pipeline.runner import run_extraction
from app.schemas.job import JobRecord


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a PDF to extracted.txt")
    parser.add_argument("pdf", type=Path, help="Path to the PDF")
    args = parser.parse_args()
    pdf = args.pdf
    if not pdf.exists():
        raise SystemExit(f"File not found: {pdf}")

    settings = get_settings()
    if not settings.credentials_ok:
        raise SystemExit(
            "Missing Google credentials. Fill .env (GCP_PROJECT_ID, "
            "DOCAI_PROCESSOR_ID) and place the service-account JSON at "
            "GOOGLE_APPLICATION_CREDENTIALS."
        )

    store = JobStore()
    job_id = uuid.uuid4().hex
    shutil.copyfile(pdf, store.source_pdf(job_id))
    store.save(
        JobRecord(
            job_id=job_id,
            source_file=pdf.name,
            status="queued",
            message="CLI job",
        )
    )
    print(f"Job {job_id} started")
    run_extraction(job_id)
    record = store.load(job_id)
    if record and record.status == "done":
        print(f"TXT: {store.result_txt(job_id)}")
        print(f"JSON: {store.result_json(job_id)}")
    else:
        raise SystemExit(f"Failed: {record.error if record else 'unknown error'}")


if __name__ == "__main__":
    main()
