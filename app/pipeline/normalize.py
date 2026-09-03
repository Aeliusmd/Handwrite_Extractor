from __future__ import annotations

from app.pipeline.digital import clean_whitespace
from app.schemas.page import ExtractionResult, PageExtraction


def normalize_page(page: PageExtraction) -> PageExtraction:
    page.printed_text = clean_whitespace(page.printed_text)
    page.full_text = clean_whitespace(page.full_text or page.printed_text)
    page.handwritten_text = clean_whitespace(page.handwritten_text)
    page.notes = [clean_whitespace(n) for n in page.notes if n and n.strip()]
    page.circled_options = [clean_whitespace(c) for c in page.circled_options if c and c.strip()]
    seen_marks: set[tuple[str, str]] = set()
    unique_marks = []
    for mark in page.marks:
        key = (mark.label.strip().lower(), mark.state)
        if key in seen_marks:
            continue
        seen_marks.add(key)
        unique_marks.append(mark)
    page.marks = unique_marks
    return page


def assemble_result(
    job_id: str,
    source_file: str,
    pages: list[PageExtraction],
) -> ExtractionResult:
    pages = [normalize_page(p) for p in sorted(pages, key=lambda item: item.page)]
    engines = sorted({p.engine for p in pages if p.engine})
    return ExtractionResult(
        job_id=job_id,
        source_file=source_file,
        page_count=len(pages),
        pages=pages,
        digital_pages=sum(1 for p in pages if p.route == "digital"),
        scanned_pages=sum(1 for p in pages if p.route.startswith("scanned")),
        vision_pages=sum(1 for p in pages if "vision" in p.route),
        engines=engines,
    )
