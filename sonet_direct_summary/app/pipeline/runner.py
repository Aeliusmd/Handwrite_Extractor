from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.pipeline.chunk import Chunk, build_chunks, pdf_page_count, split_chunk
from app.pipeline.job_store import JobStore
from app.pipeline.sonnet import TruncatedSummary, combine_summaries, summarize_chunk_pdf


def _summarize_one(store: JobStore, job_id: str, source_pdf: str, chunk: Chunk) -> str:
    result_path = store.chunk_result_path(job_id, chunk.start_page, chunk.end_page)
    if result_path.exists():
        return result_path.read_text(encoding="utf-8")
    try:
        text = summarize_chunk_pdf(str(chunk.path), chunk.page_numbers)
    except TruncatedSummary:
        parts = split_chunk(source_pdf, chunk, store.job_dir(job_id) / "chunk_pdfs")
        if len(parts) == 1:
            raise
        pieces = [_summarize_one(store, job_id, source_pdf, part) for part in parts]
        text = combine_summaries(pieces) if len(pieces) > 1 else pieces[0]
    result_path.write_text(text, encoding="utf-8")
    return text


def run_direct_summary(job_id: str) -> None:
    settings = get_settings()
    store = JobStore()
    record = store.load(job_id)
    if record is None:
        raise FileNotFoundError(f"Unknown job {job_id}")

    pdf_path = store.source_pdf(job_id)
    job_dir = store.job_dir(job_id)

    try:
        store.update(job_id, status="chunking", message="Counting PDF pages")
        total = pdf_page_count(str(pdf_path))
        store.update(
            job_id,
            page_count=total,
            pages_total=total,
            pages_done=0,
            scanned_pages=total,
            message=f"{total} pages",
        )

        chunks = build_chunks(str(pdf_path), job_dir / "chunk_pdfs")
        store.update(job_id, status="summarizing", message=f"{len(chunks)} PDF chunks to Sonnet")

        parts: list[str] = []
        for chunk in chunks:
            text = _summarize_one(store, job_id, str(pdf_path), chunk)
            parts.append(text)
            store.update(
                job_id,
                pages_done=chunk.end_page,
                current_chunk=f"{chunk.start_page}-{chunk.end_page}",
                message=f"Summarized pages {chunk.start_page}-{chunk.end_page}",
            )

        store.update(job_id, status="writing", message="Writing summary.txt")
        body = combine_summaries(parts) if len(parts) > 1 else (parts[0] if parts else "")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        header = [
            "=" * 80,
            "DOCUMENT SUMMARY",
            "=" * 80,
            f"Source file: {record.source_file}",
            f"Job ID: {job_id}",
            f"Engine: {settings.anthropic_model}",
            f"Mode: direct PDF summary",
            f"Summarized at: {stamp}",
            "",
            body.strip(),
            "",
        ]
        store.result_summary_txt(job_id).write_text("\n".join(header), encoding="utf-8")
        store.update(
            job_id,
            status="done",
            pages_done=total,
            pages_total=total,
            current_chunk=None,
            message="Summary complete",
        )
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="error", error=str(exc), message="Summary failed")
        raise
