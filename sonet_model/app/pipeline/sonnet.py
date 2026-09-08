from __future__ import annotations

import base64
import json
import logging
import re

import anthropic

from app.config import get_settings
from app.pipeline.gate import sonnet_slot
from app.pipeline.retry import retry_call
from app.schemas.page import FormField, Mark, PageExtraction, Signature, TableData

logger = logging.getLogger(__name__)


class TruncatedExtraction(RuntimeError):
    """Sonnet stopped before finishing every page."""


EXTRACT_PROMPT = """You are extracting EVERY visible detail from a medical/legal PDF packet.

The attached PDF is a slice of a larger document.
Original page numbers in the full packet: {page_list}
The first page of THIS file is original page {first_page}. Number every page using those original page numbers.

Call submit_page_extractions once with one object per page, including blank pages.
Do not skip pages. Do not invent values you cannot see.

For each page capture:
- printed text (full readable body)
- handwritten values, dates, names, phones, SSNs, case numbers
- every checkbox / tick / X: marked or unmarked with its label
- circled printed options
- margin notes, diagonal notes, "Other:" fill-ins
- tables as rows of cells
- signatures: present or absent only (do not invent a name from a scribble)

Source for a field:
- handwritten = filled by hand
- printed = typed/printed on the form
"""


EXTRACT_TOOL = {
    "name": "submit_page_extractions",
    "description": "Submit structured extraction for every page in the attached PDF.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer", "description": "Original packet page number"},
                        "document_type": {"type": ["string", "null"]},
                        "header": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "value": {"type": ["string", "null"]},
                                    "source": {"type": "string"},
                                    "value_type": {"type": ["string", "null"]},
                                },
                                "required": ["label"],
                            },
                        },
                        "marks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "state": {"type": "string", "enum": ["marked", "unmarked"]},
                                    "mark_type": {"type": ["string", "null"]},
                                },
                                "required": ["label", "state"],
                            },
                        },
                        "circled_options": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "array", "items": {"type": "string"}},
                        "signatures": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {"type": "string"},
                                    "state": {"type": "string", "enum": ["present", "absent"]},
                                },
                                "required": ["role"],
                            },
                        },
                        "tables": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "rows": {
                                        "type": "array",
                                        "items": {"type": "array", "items": {"type": "string"}},
                                    }
                                },
                            },
                        },
                        "printed_text": {"type": "string"},
                        "handwritten_text": {"type": "string"},
                        "full_text": {"type": "string"},
                        "needs_review": {"type": "boolean"},
                    },
                    "required": ["page"],
                },
            }
        },
        "required": ["pages"],
    },
}


def _client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.credentials_ok:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in sonet_model/.env")
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.strip(),
        timeout=1200.0,
    )


def _stream_message(client: anthropic.Anthropic, kwargs: dict):
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def complete_text(*, user_text: str, system: str | None = None, max_tokens: int | None = None) -> str:
    """Plain-text Sonnet completion (used by summarization)."""
    settings = get_settings()
    kwargs: dict = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens or min(16000, settings.max_output_tokens),
        "messages": [{"role": "user", "content": user_text}],
    }
    if system:
        kwargs["system"] = system

    def _call():
        with sonnet_slot():
            return _stream_message(_client(), kwargs)

    response = retry_call(_call)
    parts = [
        block.text or ""
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()


def _parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text, flags=re.MULTILINE)
        text = text.strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def _payload_from_response(response) -> dict:
    stop = getattr(response, "stop_reason", None)
    tool_payload = None
    text_parts: list[str] = []
    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(block, "name", "") == EXTRACT_TOOL["name"]:
            tool_payload = block.input
        elif btype == "text":
            text_parts.append(block.text or "")
    if stop == "max_tokens":
        raise TruncatedExtraction("Sonnet hit max_tokens before finishing the extraction")
    if isinstance(tool_payload, dict):
        return tool_payload
    if text_parts:
        return _parse_json_text("\n".join(text_parts))
    raise ValueError("Sonnet returned no extraction payload")


def _as_str_dict(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in value.items() if k}


def _page_from_dict(raw: dict, engine: str) -> PageExtraction:
    fields = []
    for item in raw.get("fields") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        fields.append(
            FormField(
                label=str(item["label"]),
                value=None if item.get("value") is None else str(item.get("value")),
                source=str(item.get("source") or "sonnet"),
                value_type=None if item.get("value_type") is None else str(item.get("value_type")),
            )
        )
    marks = []
    for item in raw.get("marks") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        state = str(item.get("state") or "unmarked").lower()
        marks.append(
            Mark(
                label=str(item["label"]),
                state="marked" if state == "marked" else "unmarked",
                mark_type=None if item.get("mark_type") is None else str(item.get("mark_type")),
            )
        )
    signatures = []
    for item in raw.get("signatures") or []:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "present").lower()
        signatures.append(
            Signature(
                role=str(item.get("role") or "unknown"),
                state="absent" if state == "absent" else "present",
            )
        )
    tables = []
    for item in raw.get("tables") or []:
        rows = item.get("rows") if isinstance(item, dict) else None
        if not rows:
            continue
        tables.append(
            TableData(rows=[[str(cell) for cell in row] for row in rows if isinstance(row, list)])
        )
    document_type = raw.get("document_type")
    if document_type is not None and not isinstance(document_type, str):
        document_type = str(document_type)
    return PageExtraction(
        page=int(raw["page"]),
        route="sonnet",
        document_type=document_type,
        header=_as_str_dict(raw.get("header")),
        fields=fields,
        marks=marks,
        circled_options=[str(x) for x in (raw.get("circled_options") or []) if x],
        notes=[str(x) for x in (raw.get("notes") or []) if x],
        signatures=signatures,
        tables=tables,
        printed_text=str(raw.get("printed_text") or ""),
        handwritten_text=str(raw.get("handwritten_text") or ""),
        full_text=str(raw.get("full_text") or raw.get("printed_text") or ""),
        needs_review=bool(raw.get("needs_review")),
        engine=engine,
    )


def remap_pages(pages: list[PageExtraction], page_numbers: list[int], engine: str) -> list[PageExtraction]:
    expected = set(page_numbers)
    if pages and all(p.page in expected for p in pages):
        by_page = {p.page: p for p in pages}
    else:
        ordered = sorted(pages, key=lambda item: item.page)
        by_page = {}
        for index, page in enumerate(ordered):
            if index >= len(page_numbers):
                break
            page.page = page_numbers[index]
            by_page[page.page] = page

    result: list[PageExtraction] = []
    for number in page_numbers:
        page = by_page.get(number)
        if page is None:
            page = PageExtraction(
                page=number,
                route="sonnet",
                engine=engine,
                needs_review=True,
                warnings=["Page missing from Sonnet response"],
            )
        result.append(page)
    if len(by_page) < len(page_numbers):
        raise TruncatedExtraction(
            f"Sonnet returned {len(by_page)} pages, expected {len(page_numbers)}"
        )
    return result


def extract_chunk_pdf(pdf_path: str, page_numbers: list[int]) -> list[PageExtraction]:
    settings = get_settings()
    engine = settings.anthropic_model
    prompt = EXTRACT_PROMPT.format(
        page_list=", ".join(str(n) for n in page_numbers),
        first_page=page_numbers[0],
    )
    with open(pdf_path, "rb") as handle:
        encoded = base64.standard_b64encode(handle.read()).decode("ascii")

    def _call():
        with sonnet_slot():
            kwargs = {
                "model": settings.anthropic_model,
                "max_tokens": settings.max_output_tokens,
                "tools": [EXTRACT_TOOL],
                "tool_choice": {"type": "tool", "name": EXTRACT_TOOL["name"]},
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": encoded,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            }
            client = _client()
            try:
                return _stream_message(client, kwargs)
            except TypeError:
                kwargs.pop("tool_choice", None)
                return _stream_message(client, kwargs)

    response = retry_call(_call)
    try:
        payload = _payload_from_response(response)
        raw_pages = payload.get("pages") if isinstance(payload, dict) else None
        if not isinstance(raw_pages, list):
            raise ValueError("Sonnet payload missing pages[]")
        pages = [
            _page_from_dict(item, engine)
            for item in raw_pages
            if isinstance(item, dict) and "page" in item
        ]
        return remap_pages(pages, page_numbers, engine)
    except TruncatedExtraction:
        raise
    except Exception as exc:
        if len(page_numbers) > 1:
            raise TruncatedExtraction(str(exc)) from exc
        raise
