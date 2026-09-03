from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class Chunk:
    path: Path
    start_page: int
    end_page: int
    page_numbers: list[int]


def consecutive_groups(pages: list[int]) -> list[list[int]]:
    if not pages:
        return []
    ordered = sorted(pages)
    groups: list[list[int]] = [[ordered[0]]]
    for page in ordered[1:]:
        if page == groups[-1][-1] + 1:
            groups[-1].append(page)
        else:
            groups.append([page])
    return groups


def build_scan_chunks(
    pdf_path: str,
    scanned_pages: list[int],
    output_dir: Path,
    chunk_size: int = 15,
) -> list[Chunk]:
    """Build <=chunk_size PDFs from consecutive scanned pages (Form Parser online limit)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source = fitz.open(pdf_path)
    chunks: list[Chunk] = []
    try:
        for group in consecutive_groups(scanned_pages):
            for offset in range(0, len(group), chunk_size):
                page_numbers = group[offset : offset + chunk_size]
                start = page_numbers[0]
                end = page_numbers[-1]
                part = fitz.open()
                for page_number in page_numbers:
                    part.insert_pdf(
                        source,
                        from_page=page_number - 1,
                        to_page=page_number - 1,
                    )
                path = output_dir / f"chunk_{start:04d}_{end:04d}.pdf"
                part.save(path)
                part.close()
                chunks.append(
                    Chunk(
                        path=path,
                        start_page=start,
                        end_page=end,
                        page_numbers=page_numbers,
                    )
                )
    finally:
        source.close()
    return chunks


def render_page_png(pdf_path: str, page_number: int, output_path: Path, dpi: int = 220) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(str(output_path))
    finally:
        doc.close()
    return output_path
