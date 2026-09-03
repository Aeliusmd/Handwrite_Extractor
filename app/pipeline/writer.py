from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.page import ExtractionResult, PageExtraction


def _section(title: str) -> str:
    return f"\n--- {title} ---\n"


def render_page(page: PageExtraction) -> str:
    lines = [
        "=" * 80,
        f"PAGE {page.page}",
        "=" * 80,
        f"Route: {page.route}",
        f"Engine: {page.engine or 'n/a'}",
    ]
    if page.document_type:
        lines.append(f"Document type: {page.document_type}")
    if page.confidence is not None:
        lines.append(f"OCR confidence: {page.confidence:.2f}")
    if page.needs_review:
        lines.append("Needs review: yes")
    if page.warnings:
        lines.append("Warnings: " + "; ".join(page.warnings))

    if page.header:
        lines.append(_section("HEADER"))
        for key, value in page.header.items():
            lines.append(f"{key}: {value}")

    if page.fields:
        lines.append(_section("FORM FIELDS"))
        for field in page.fields:
            value = field.value if field.value else ""
            extra = f" [{field.source}]"
            if field.value_type:
                extra += f" ({field.value_type})"
            lines.append(f"{field.label}: {value}{extra}")

    if page.marks:
        lines.append(_section("CHECKBOXES / MARKS"))
        for mark in page.marks:
            state = "MARKED" if mark.state == "marked" else "UNMARKED"
            kind = f" ({mark.mark_type})" if mark.mark_type else ""
            lines.append(f"{mark.label}: {state}{kind}")

    if page.circled_options:
        lines.append(_section("CIRCLED OPTIONS"))
        for item in page.circled_options:
            lines.append(f"- {item}")

    if page.notes:
        lines.append(_section("HANDWRITTEN NOTES"))
        for item in page.notes:
            lines.append(f"- {item}")

    if page.handwritten_text:
        lines.append(_section("HANDWRITTEN TEXT"))
        lines.append(page.handwritten_text)

    if page.signatures:
        lines.append(_section("SIGNATURES"))
        for sig in page.signatures:
            lines.append(f"{sig.role}: {sig.state.upper()}")

    if page.tables:
        lines.append(_section("TABLES"))
        for index, table in enumerate(page.tables, start=1):
            lines.append(f"[Table {index}]")
            for row in table.rows:
                lines.append(" | ".join(cell.replace("\n", " ") for cell in row))
            lines.append("")

    body = page.full_text or page.printed_text
    if body:
        lines.append(_section("FULL TEXT"))
        lines.append(body)

    lines.append("")
    return "\n".join(lines)


def render_txt(result: ExtractionResult) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = [
        "=" * 80,
        "DOCUMENT EXTRACTION",
        "=" * 80,
        f"Source file: {result.source_file}",
        f"Job ID: {result.job_id}",
        f"Pages: {result.page_count}",
        f"Digital pages: {result.digital_pages}",
        f"Scanned pages: {result.scanned_pages}",
        f"Vision-rescued pages: {result.vision_pages}",
        f"Engines: {', '.join(result.engines) or 'n/a'}",
        f"Extracted at: {stamp}",
        "",
        "This file contains printed text, handwritten values, checkboxes,",
        "circled options, notes, tables, and signature presence flags.",
        "",
    ]
    body = [render_page(page) for page in result.pages]
    return "\n".join(header + body).rstrip() + "\n"
