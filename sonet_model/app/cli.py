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
    parser = argparse.ArgumentParser(description="Extract a PDF with Claude Sonnet 5")
    parser.add_argument("pdf", type=Path, help="Path to the PDF")
    parser.add_argument("--user-id", default=None, help="Optional uploader user id")
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Process in this process instead of leaving the job unprocessed for the worker",
    )
    args = parser.parse_args()
    pdf = args.pdf
    if not pdf.exists():
        raise SystemExit(f"File not found: {pdf}")

    settings = get_settings()
    if not settings.credentials_ok:
        raise SystemExit("Missing ANTHROPIC_API_KEY in sonet_model/.env")

    store = JobStore()
    job_id = uuid.uuid4().hex
    shutil.copyfile(pdf, store.source_pdf(job_id))
    store.save(
        JobRecord(
            job_id=job_id,
            source_file=pdf.name,
            user_id=args.user_id,
            pdf_size_bytes=pdf.stat().st_size,
            status="queued",
            message="CLI job",
        )
    )
    print(f"Job {job_id} queued as unprocessed")
    if args.inline or settings.inline_extract:
        print(f"Job {job_id} started inline")
        run_extraction(job_id)
        record = store.load(job_id)
        if record and record.status == "done":
            print(f"TXT: {store.result_txt(job_id)}")
            print(f"JSON: {store.result_json(job_id)}")
            summary = store.result_summary_txt(job_id)
            if summary.exists():
                print(f"SUMMARY: {summary}")
        else:
            raise SystemExit(f"Failed: {record.error if record else 'unknown error'}")
    else:
        print("Start the worker to process it: python -m app.worker")


if __name__ == "__main__":
    main()
