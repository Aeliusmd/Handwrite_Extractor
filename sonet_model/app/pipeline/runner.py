from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import get_settings
from app.pipeline.chunk import Chunk, build_chunks, pdf_page_count, split_chunk
from app.pipeline.job_store import JobStore
from app.pipeline.normalize import assemble_result
from app.pipeline.sonnet import TruncatedExtraction, extract_chunk_pdf
from app.pipeline.summarize import run_summarization
from app.pipeline.writer import render_txt
from app.schemas.page import PageExtraction


def _extract_one(store: JobStore, job_id: str, source_pdf: str, chunk: Chunk) -> list[dict]:
    result_path = store.chunk_result_path(job_id, chunk.start_page, chunk.end_page)
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    try:
        pages = extract_chunk_pdf(str(chunk.path), chunk.page_numbers)
    except TruncatedExtraction:
        parts = split_chunk(source_pdf, chunk, store.job_dir(job_id) / "chunk_pdfs")
        if len(parts) == 1:
            raise
        payload: list[dict] = []
        for part in parts:
            payload.extend(_extract_one(store, job_id, source_pdf, part))
        result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload
    payload = [json.loads(p.model_dump_json()) for p in pages]
    result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def run_extraction(job_id: str) -> None:
    settings = get_settings()
    store = JobStore()
    record = store.load(job_id)
    if record is None:
        raise FileNotFoundError(f"Unknown job {job_id}")

    pdf_path = store.source_pdf(job_id)
    job_dir = store.job_dir(job_id)

    try:
        store.update(job_id, status="classifying", message="Counting PDF pages")
        total = pdf_page_count(str(pdf_path))
        store.update(
            job_id,
            page_count=total,
            pages_total=total,
            pages_done=0,
            digital_pages=0,
            scanned_pages=total,
            message=f"{total} pages",
        )

        store.update(job_id, status="chunking", message="Building Sonnet PDF chunks")
        chunks = build_chunks(str(pdf_path), job_dir / "chunk_pdfs")
        store.update(job_id, message=f"{len(chunks)} Sonnet chunks")

        store.update(job_id, status="extracting_scans", message="Sending PDF to Claude Sonnet 5")
        pending = []
        for chunk in chunks:
            result_path = store.chunk_result_path(job_id, chunk.start_page, chunk.end_page)
            if result_path.exists():
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                for page_data in payload:
                    store.save_page(job_id, page_data)
                continue
            pending.append(chunk)

        if pending:
            workers = max(1, min(settings.max_parallel_chunks, len(pending)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_extract_one, store, job_id, str(pdf_path), chunk): chunk
                    for chunk in pending
                }
                for future in as_completed(futures):
                    chunk = futures[future]
                    payload = future.result()
                    for page_data in payload:
                        store.save_page(job_id, page_data)
                    done = len(list((job_dir / "pages").glob("*.json")))
                    store.update(
                        job_id,
                        pages_done=done,
                        current_chunk=f"{chunk.start_page}-{chunk.end_page}",
                        message=f"Sonnet pages {chunk.start_page}-{chunk.end_page}",
                    )

        pages = [PageExtraction.model_validate(item) for item in store.load_pages(job_id)]
        store.update(job_id, status="normalizing", message="Assembling transcript")
        result = assemble_result(job_id, record.source_file, pages, settings.anthropic_model)

        store.update(job_id, status="writing", message="Writing extracted.txt")
        store.result_json(job_id).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        store.result_txt(job_id).write_text(render_txt(result), encoding="utf-8")

        latest = store.load(job_id) or record
        warnings = list(latest.warnings)
        if settings.enable_summarization:
            store.update(job_id, status="summarizing", message="Summarizing extracted.txt")
            try:
                run_summarization(store, job_id)
                done_message = "Extraction and summary complete"
            except Exception as exc:  # noqa: BLE001
                warning = f"Summary failed: {exc}"
                warnings.append(warning)
                store.update(job_id, warnings=warnings, message=warning)
                done_message = "Extraction complete; summary failed"
        else:
            done_message = "Extraction complete"

        store.update(
            job_id,
            status="done",
            pages_done=result.page_count,
            pages_total=result.page_count,
            digital_pages=0,
            scanned_pages=result.page_count,
            vision_pages=0,
            current_chunk=None,
            warnings=warnings,
            message=done_message,
        )
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="error", error=str(exc), message="Extraction failed")
        raise
