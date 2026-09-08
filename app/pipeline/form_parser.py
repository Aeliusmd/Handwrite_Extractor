from __future__ import annotations

from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai

from app.config import get_settings
from app.pipeline.digital import clean_whitespace, guess_document_type
from app.pipeline.google_gate import docai_slot
from app.pipeline.retry import retry_call
from app.schemas.page import FormField, Mark, PageExtraction, TableData


def _text_from_anchor(document: documentai.Document, layout) -> str:
    if not layout or not layout.text_anchor or not layout.text_anchor.text_segments:
        return ""
    full = document.text or ""
    parts: list[str] = []
    for segment in layout.text_anchor.text_segments:
        start = int(segment.start_index or 0)
        end = int(segment.end_index or 0)
        parts.append(full[start:end])
    return clean_whitespace("".join(parts))


def _page_text(document: documentai.Document, page: documentai.Document.Page) -> str:
    if page.layout:
        text = _text_from_anchor(document, page.layout)
        if text:
            return text
    paragraphs = [_text_from_anchor(document, para.layout) for para in page.paragraphs]
    return clean_whitespace("\n".join(p for p in paragraphs if p))


def _is_checkbox(value_type: str) -> bool:
    return "checkbox" in (value_type or "").lower() or "unfilled" in (value_type or "").lower() or "filled" in (value_type or "").lower()


def _source_for_field(value_type: str, value: str) -> str:
    if _is_checkbox(value_type):
        return "printed_ocr"
    if value and len(value) <= 80:
        return "handwritten"
    return "printed_ocr"


def document_to_pages(
    document: documentai.Document,
    page_numbers: list[int],
) -> list[PageExtraction]:
    pages: list[PageExtraction] = []
    for index, page in enumerate(document.pages):
        original_page = page_numbers[index] if index < len(page_numbers) else page_numbers[-1]
        full_text = _page_text(document, page)
        fields: list[FormField] = []
        marks: list[Mark] = []
        tables: list[TableData] = []
        confidences: list[float] = []

        for form_field in page.form_fields:
            label = _text_from_anchor(document, form_field.field_name)
            value = _text_from_anchor(document, form_field.field_value)
            value_type = (form_field.value_type or "").strip()
            if form_field.field_value and form_field.field_value.confidence:
                confidences.append(float(form_field.field_value.confidence))
            if not label and not value:
                continue
            if _is_checkbox(value_type):
                marked = "unfilled" not in value_type.lower() and (
                    "filled" in value_type.lower()
                    or value.lower() in {"yes", "checked", "x", "✓", "true"}
                )
                if "unfilled" in value_type.lower():
                    marked = False
                if "filled" in value_type.lower() and "unfilled" not in value_type.lower():
                    marked = True
                marks.append(
                    Mark(
                        label=label or value or "checkbox",
                        state="marked" if marked else "unmarked",
                        mark_type="checkbox",
                    )
                )
            fields.append(
                FormField(
                    label=label or "field",
                    value=value or None,
                    source=_source_for_field(value_type, value),
                    value_type=value_type or None,
                )
            )

        for table in page.tables:
            rows: list[list[str]] = []
            for row in list(table.header_rows) + list(table.body_rows):
                rows.append([_text_from_anchor(document, cell.layout) for cell in row.cells])
            if rows:
                tables.append(TableData(rows=rows))

        avg_conf = sum(confidences) / len(confidences) if confidences else None
        pages.append(
            PageExtraction(
                page=original_page,
                route="scanned",
                document_type=guess_document_type(full_text),
                fields=fields,
                marks=marks,
                tables=tables,
                printed_text=full_text,
                full_text=full_text,
                confidence=avg_conf,
                needs_review=bool(avg_conf is not None and avg_conf < 0.6),
                engine="google-documentai-form-parser",
            )
        )
    return pages


def process_chunk_pdf(pdf_path: str, page_numbers: list[int]) -> list[PageExtraction]:
    settings = get_settings()
    if not settings.gcp_project_id or not settings.docai_processor_id:
        raise RuntimeError("GCP_PROJECT_ID and DOCAI_PROCESSOR_ID must be set in .env")

    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(
            api_endpoint=f"{settings.docai_location}-documentai.googleapis.com"
        )
    )
    name = client.processor_path(
        settings.gcp_project_id,
        settings.docai_location,
        settings.docai_processor_id,
    )
    with open(pdf_path, "rb") as handle:
        content = handle.read()

    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(
            content=content,
            mime_type="application/pdf",
        ),
    )
    if hasattr(request, "imageless_mode"):
        request.imageless_mode = True
    def _call():
        with docai_slot():
            return client.process_document(request=request)

    result = retry_call(_call)
    return document_to_pages(result.document, page_numbers)
