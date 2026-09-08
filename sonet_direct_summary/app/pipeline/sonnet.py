from __future__ import annotations

import base64

import anthropic

from app.config import get_settings
from app.pipeline.gate import sonnet_slot
from app.pipeline.prompt import COMBINE_PROMPT, SUMMARIZE_PROMPT, SUMMARIZE_SYSTEM
from app.pipeline.retry import retry_call


class TruncatedSummary(RuntimeError):
    """Sonnet stopped before finishing the summary."""


def _client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.credentials_ok:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in sonet_direct_summary/.env")
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.strip(),
        timeout=1200.0,
    )


def _stream_message(client: anthropic.Anthropic, kwargs: dict):
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def _text_from_response(response) -> str:
    stop = getattr(response, "stop_reason", None)
    if stop == "max_tokens":
        raise TruncatedSummary("Sonnet hit max_tokens before finishing the summary")
    parts = [
        block.text or ""
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()


def summarize_chunk_pdf(pdf_path: str, page_numbers: list[int]) -> str:
    settings = get_settings()
    prompt = SUMMARIZE_PROMPT.format(
        page_list=", ".join(str(n) for n in page_numbers),
        first_page=page_numbers[0],
    )
    with open(pdf_path, "rb") as handle:
        encoded = base64.standard_b64encode(handle.read()).decode("ascii")

    kwargs = {
        "model": settings.anthropic_model,
        "max_tokens": settings.summary_max_tokens,
        "system": SUMMARIZE_SYSTEM,
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

    def _call():
        with sonnet_slot():
            return _stream_message(_client(), kwargs)

    return _text_from_response(retry_call(_call))


def _concat_parts(parts: list[str]) -> str:
    blocks = [part.strip() for part in parts if part and part.strip()]
    return "\n\n".join(blocks)


def combine_summaries(parts: list[str]) -> str:
    settings = get_settings()
    joined = "\n\n---- PART BREAK ----\n\n".join(
        f"PART {i}\n{part}" for i, part in enumerate(parts, start=1)
    )
    kwargs = {
        "model": settings.anthropic_model,
        "max_tokens": max(settings.summary_max_tokens, settings.max_output_tokens),
        "system": SUMMARIZE_SYSTEM,
        "messages": [{"role": "user", "content": COMBINE_PROMPT + joined}],
    }

    def _call():
        with sonnet_slot():
            return _stream_message(_client(), kwargs)

    try:
        return _text_from_response(retry_call(_call))
    except TruncatedSummary:
        return _concat_parts(parts)
