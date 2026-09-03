from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import get_settings
from app.pipeline.chunk import build_scan_chunks, render_page_png
from app.pipeline.classify import classify_pdf
from app.pipeline.digital import extract_digital_pages
from app.pipeline.form_parser import process_chunk_pdf
from app.pipeline.job_store import JobStore
from app.pipeline.normalize import assemble_result
from app.pipeline.vision_rescue import analyze_page_image, merge_vision, select_vision_pages
from app.pipeline.writer import render_txt
from app.schemas.page import PageExtraction


def _save_extraction(store: JobStore, job_id: str, page: PageExtraction) -> None:
    store.save_page(job_id, json.loads(page.model_dump_json()))


def run_extraction(job_id: str) -> None:
    settings = get_settings()
    store = JobStore()
    record = store.load(job_id)
    if record is None:
        raise FileNotFoundError(f"Unknown job {job_id}")

    pdf_path = store.source_pdf(job_id)
    job_dir = store.job_dir(job_id)

    try:
        store.update(job_id, status="classifying", message="Classifying pages")
        classes = classify_pdf(str(pdf_path), threshold=settings.digital_char_threshold)
        digital_pages = [item.page for item in classes if item.route == "digital"]
        scanned_pages = [item.page for item in classes if item.route == "scanned"]
        store.update(
            job_id,
            page_count=len(classes),
            pages_total=len(classes),
            pages_done=0,
            digital_pages=len(digital_pages),
            scanned_pages=len(scanned_pages),
            message=f"{len(digital_pages)} digital, {len(scanned_pages)} scanned",
        )

        store.update(job_id, status="extracting_digital", message="Extracting digital pages")
        missing_digital = [
            page for page in digital_pages if not store.page_path(job_id, page).exists()
        ]
        for extraction in extract_digital_pages(str(pdf_path), missing_digital):
            _save_extraction(store, job_id, extraction)
        store.update(
            job_id,
            pages_done=len(list((job_dir / "pages").glob("*.json"))),
            message=f"Extracted {len(missing_digital)} digital pages",
        )

        store.update(job_id, status="chunking", message="Building scan chunks")
        chunks = build_scan_chunks(
            str(pdf_path),
            scanned_pages,
            job_dir / "chunk_pdfs",
            chunk_size=settings.chunk_size,
        )
        store.update(job_id, message=f"{len(chunks)} scan chunks")

        store.update(job_id, status="extracting_scans", message="Running Form Parser")
        pending = []
        for chunk in chunks:
            result_path = store.chunk_result_path(job_id, chunk.start_page, chunk.end_page)
            if result_path.exists():
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                for page_data in payload:
                    store.save_page(job_id, page_data)
                continue
            pending.append(chunk)

        def _run_chunk(chunk):
            pages = process_chunk_pdf(str(chunk.path), chunk.page_numbers)
            payload = [json.loads(p.model_dump_json()) for p in pages]
            path = store.chunk_result_path(job_id, chunk.start_page, chunk.end_page)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return chunk, payload

        if pending:
            with ThreadPoolExecutor(max_workers=settings.max_parallel_chunks) as pool:
                futures = {pool.submit(_run_chunk, chunk): chunk for chunk in pending}
                for future in as_completed(futures):
                    chunk, payload = future.result()
                    for page_data in payload:
                        store.save_page(job_id, page_data)
                    done = len(list((job_dir / "pages").glob("*.json")))
                    store.update(
                        job_id,
                        pages_done=done,
                        current_chunk=f"{chunk.start_page}-{chunk.end_page}",
                        message=f"Form Parser pages {chunk.start_page}-{chunk.end_page}",
                    )

        pages = [
            PageExtraction.model_validate(item) for item in store.load_pages(job_id)
        ]

        vision_count = 0
        if settings.enable_vision_rescue and scanned_pages:
            store.update(job_id, status="vision_rescue", message="Selecting messy pages for Gemini")
            selected = select_vision_pages(pages, settings.vision_max_pages)
            by_page = {p.page: p for p in pages}
            abort_vision = False
            for page_number in selected:
                if abort_vision or "vision" in by_page[page_number].route:
                    continue
                try:
                    png_path = job_dir / "vision" / f"{page_number:04d}.png"
                    render_page_png(
                        str(pdf_path),
                        page_number,
                        png_path,
                        dpi=settings.vision_dpi,
                    )
                    vision = analyze_page_image(png_path.read_bytes())
                    merged = merge_vision(by_page[page_number], vision)
                    by_page[page_number] = merged
                    _save_extraction(store, job_id, merged)
                    vision_count += 1
                    store.update(
                        job_id,
                        vision_pages=vision_count,
                        message=f"Vision rescue page {page_number}",
                    )
                    png_path.unlink(missing_ok=True)
                except Exception as exc:  # noqa: BLE001
                    warning = f"Vision skipped page {page_number}: {exc}"
                    record = store.load(job_id)
                    warnings = list(record.warnings) if record else []
                    warnings.append(warning)
                    if page_number in by_page:
                        by_page[page_number].warnings.append(warning)
                        _save_extraction(store, job_id, by_page[page_number])
                    text = str(exc).lower()
                    if any(
                        token in text
                        for token in (
                            "unauthenticated",
                            "permission",
                            "api has not been used",
                            "403",
                            "401",
                        )
                    ):
                        abort_vision = True
                        warnings.append("Vision rescue stopped; Form Parser results will still be written.")
                    store.update(job_id, warnings=warnings, message=warning)
            pages = list(by_page.values())

        store.update(job_id, status="normalizing", message="Assembling transcript")
        result = assemble_result(job_id, record.source_file, pages)

        store.update(job_id, status="writing", message="Writing extracted.txt")
        store.result_json(job_id).write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        store.result_txt(job_id).write_text(render_txt(result), encoding="utf-8")

        store.update(
            job_id,
            status="done",
            pages_done=result.page_count,
            pages_total=result.page_count,
            digital_pages=result.digital_pages,
            scanned_pages=result.scanned_pages,
            vision_pages=result.vision_pages,
            current_chunk=None,
            message="Extraction complete",
        )
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="error", error=str(exc), message="Extraction failed")
        raise
