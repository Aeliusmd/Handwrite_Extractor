from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass
class PageClass:
    page: int
    route: str
    chars: int
    image_count: int


def classify_pdf(pdf_path: str, threshold: int = 80) -> list[PageClass]:
    """Route each page to digital (PyMuPDF) or scanned (Form Parser)."""
    doc = fitz.open(pdf_path)
    results: list[PageClass] = []
    try:
        for index, page in enumerate(doc):
            text = page.get_text("text") or ""
            chars = len(text.strip())
            images = page.get_images(full=True)
            if chars > threshold:
                route = "digital"
            elif images:
                route = "scanned"
            else:
                route = "digital"
            results.append(
                PageClass(
                    page=index + 1,
                    route=route,
                    chars=chars,
                    image_count=len(images),
                )
            )
    finally:
        doc.close()
    return results
