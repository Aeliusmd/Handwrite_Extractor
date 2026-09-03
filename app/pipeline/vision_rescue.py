from __future__ import annotations

import json
import re

from app.config import get_settings
from app.pipeline.retry import retry_call
from app.schemas.page import FormField, Mark, PageExtraction, Signature

VISION_PROMPT = """You are extracting EVERY visible detail from a scanned medical/legal form page.

Return ONLY valid JSON with this shape:
{
  "document_type": "string or null",
  "header": {"label": "value"},
  "fields": [{"label": "...", "value": "...", "source": "handwritten|printed_ocr"}],
  "marks": [{"label": "option text next to the box", "state": "marked|unmarked", "mark_type": "checkbox|x|tick"}],
  "circled_options": ["printed words that were circled by hand"],
  "notes": ["freehand notes, margin notes, diagonal/vertical notes"],
  "signatures": [{"role": "patient|collector|authorized_by|unknown", "state": "present|absent"}],
  "handwritten_text": "all handwritten words that are not already in fields/notes, joined",
  "printed_text": "important printed body text if needed"
}

Rules:
- Include handwritten field values, dates, phones, names.
- Every checkbox/tick/X: marked or unmarked with its label.
- Circled printed options go in circled_options, not as checkboxes.
- Signatures: present/absent only. Do not invent a name from a scribble.
- Do not omit empty unmarked boxes if you can read their labels.
- If a checkbox says Other and has handwritten text, put that text in fields/notes too.
"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text)
        text = text.strip()
    return json.loads(text)


def score_for_vision(page: PageExtraction) -> float:
    score = 0.0
    score += len(page.marks) * 3
    score += len(page.fields) * 1.2
    score += len(page.tables) * 0.5
    if page.confidence is not None:
        score += (1.0 - page.confidence) * 4
    if page.needs_review:
        score += 5
    text = page.full_text or ""
    if any(word in text.upper() for word in ("CHECK", "AUTHORIZATION", "CCF", "HIPAA", "FLOWSHEET")):
        score += 2
    return score


def select_vision_pages(pages: list[PageExtraction], max_pages: int) -> list[int]:
    scanned = [p for p in pages if p.route == "scanned"]
    if not scanned or max_pages <= 0:
        return []
    percent_cap = max(1, int(len(scanned) * 0.08))
    cap = min(max_pages, 40, max(percent_cap, min(8, len(scanned))))
    ranked = sorted(scanned, key=score_for_vision, reverse=True)
    return [p.page for p in ranked[:cap]]


def analyze_page_image(image_bytes: str | bytes, mime_type: str = "image/png") -> dict:
    settings = get_settings()
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.vertex_location,
    )
    if isinstance(image_bytes, str):
        image_bytes = image_bytes.encode("utf-8")

    def _call():
        return client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                VISION_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

    response = retry_call(_call)
    text = response.text or "{}"
    return _parse_json(text)


def merge_vision(page: PageExtraction, vision: dict) -> PageExtraction:
    page.route = "scanned+vision"
    page.engine = f"{page.engine}+{get_settings().gemini_model}"
    if vision.get("document_type") and not page.document_type:
        page.document_type = vision["document_type"]
    header = vision.get("header") or {}
    if isinstance(header, dict):
        page.header.update({str(k): str(v) for k, v in header.items() if v})

    existing_fields = {(f.label.strip().lower(), (f.value or "").strip().lower()) for f in page.fields}
    for item in vision.get("fields") or []:
        label = str(item.get("label") or "").strip()
        value = item.get("value")
        value = str(value).strip() if value is not None else None
        key = (label.lower(), (value or "").lower())
        if not label or key in existing_fields:
            continue
        page.fields.append(
            FormField(
                label=label,
                value=value,
                source=str(item.get("source") or "vision"),
            )
        )
        existing_fields.add(key)

    vision_marks = {
        str(item.get("label") or "").strip().lower(): item
        for item in vision.get("marks") or []
        if item.get("label")
    }
    if vision_marks:
        by_label = {m.label.strip().lower(): m for m in page.marks}
        for label_key, item in vision_marks.items():
            state = "marked" if str(item.get("state")) == "marked" else "unmarked"
            mark_type = item.get("mark_type")
            if label_key in by_label:
                existing = by_label[label_key]
                if existing.state != state:
                    existing.state = state
                    page.needs_review = True
                    page.warnings.append(f"mark conflict resolved by vision: {existing.label}")
                if mark_type:
                    existing.mark_type = str(mark_type)
            else:
                page.marks.append(
                    Mark(
                        label=str(item["label"]).strip(),
                        state=state,
                        mark_type=str(mark_type) if mark_type else "checkbox",
                    )
                )

    for option in vision.get("circled_options") or []:
        text = str(option).strip()
        if text and text not in page.circled_options:
            page.circled_options.append(text)

    for note in vision.get("notes") or []:
        text = str(note).strip()
        if text and text not in page.notes:
            page.notes.append(text)

    if vision.get("handwritten_text"):
        extra = str(vision["handwritten_text"]).strip()
        if extra:
            page.handwritten_text = (
                extra if not page.handwritten_text else page.handwritten_text + "\n" + extra
            )

    for sig in vision.get("signatures") or []:
        role = str(sig.get("role") or "unknown").strip() or "unknown"
        state = "present" if str(sig.get("state")) != "absent" else "absent"
        if not any(s.role == role and s.state == state for s in page.signatures):
            page.signatures.append(Signature(role=role, state=state))

    return page
