from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from app.config import get_settings


@dataclass
class Chunk:
    path: Path
    start_page: int
    end_page: int
    page_numbers: list[int]


def pdf_page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def _save_range(source: fitz.Document, page_numbers: list[int], path: Path) -> None:
    part = fitz.open()
    try:
        for page_number in page_numbers:
            part.insert_pdf(source, from_page=page_number - 1, to_page=page_number - 1)
        part.save(path)
    finally:
        part.close()


def build_chunks(pdf_path: str, output_dir: Path) -> list[Chunk]:
    settings = get_settings()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = fitz.open(pdf_path)
    chunks: list[Chunk] = []
    max_pages = settings.effective_chunk_pages()
    max_bytes = settings.max_chunk_bytes
    try:
        total = len(source)
        start = 1
        while start <= total:
            end = min(start + max_pages - 1, total)
            page_numbers = list(range(start, end + 1))
            path = output_dir / f"chunk_{page_numbers[0]:04d}_{page_numbers[-1]:04d}.pdf"
            _save_range(source, page_numbers, path)
            while path.stat().st_size > max_bytes and len(page_numbers) > 1:
                path.unlink(missing_ok=True)
                page_numbers = page_numbers[: max(1, len(page_numbers) // 2)]
                path = output_dir / f"chunk_{page_numbers[0]:04d}_{page_numbers[-1]:04d}.pdf"
                _save_range(source, page_numbers, path)
            chunks.append(
                Chunk(
                    path=path,
                    start_page=page_numbers[0],
                    end_page=page_numbers[-1],
                    page_numbers=page_numbers,
                )
            )
            start = page_numbers[-1] + 1
    finally:
        source.close()
    return chunks


def split_chunk(source_pdf: str, chunk: Chunk, output_dir: Path) -> list[Chunk]:
    if len(chunk.page_numbers) <= 1:
        return [chunk]
    mid = len(chunk.page_numbers) // 2
    left_pages = chunk.page_numbers[:mid]
    right_pages = chunk.page_numbers[mid:]
    output_dir.mkdir(parents=True, exist_ok=True)
    source = fitz.open(source_pdf)
    parts: list[Chunk] = []
    try:
        for page_numbers in (left_pages, right_pages):
            path = output_dir / f"chunk_{page_numbers[0]:04d}_{page_numbers[-1]:04d}.pdf"
            if not path.exists():
                _save_range(source, page_numbers, path)
            parts.append(
                Chunk(
                    path=path,
                    start_page=page_numbers[0],
                    end_page=page_numbers[-1],
                    page_numbers=page_numbers,
                )
            )
    finally:
        source.close()
    return parts
