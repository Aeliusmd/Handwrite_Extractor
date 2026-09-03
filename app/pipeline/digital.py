from __future__ import annotations

import re

import fitz

from app.schemas.page import PageExtraction


def guess_document_type(text: str) -> str | None:
    upper = text.upper()
    checks = [
        ("CUSTODY AND CONTROL", "Drug Testing Custody and Control Form"),
        ("TREATMENT AUTHORIZATION", "Treatment Authorization"),
        ("AUTHORIZATION FOR EXAMINATION", "Authorization for Examination or Treatment"),
        ("HIPAA", "HIPAA Release"),
        ("NON-INJURY FLOWSHEET", "Non-Injury Flowsheet"),
        ("DRIVER LICENSE", "Identification Document"),
        ("SUBPOENA", "Subpoena / Legal Declaration"),
        ("RECORDS CLASSIFICATION", "Records Classification"),
        ("OVERVIEW HIGHLIGHTS", "Overview Highlights"),
        ("PATIENT INFORMATION", "Patient Information Form"),
    ]
    for needle, label in checks:
        if needle in upper:
            return label
    return None


def _from_open_doc(doc: fitz.Document, page_number: int) -> PageExtraction:
    page = doc[page_number - 1]
    text = (page.get_text("text") or "").strip()
    header: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key and value and len(key) <= 40 and len(header) < 12:
                header[key] = value
    return PageExtraction(
        page=page_number,
        route="digital",
        document_type=guess_document_type(text),
        header=header,
        printed_text=text,
        full_text=text,
        engine="pymupdf",
    )


def extract_digital_page(pdf_path: str, page_number: int) -> PageExtraction:
    doc = fitz.open(pdf_path)
    try:
        return _from_open_doc(doc, page_number)
    finally:
        doc.close()


def extract_digital_pages(pdf_path: str, page_numbers: list[int]) -> list[PageExtraction]:
    doc = fitz.open(pdf_path)
    try:
        return [_from_open_doc(doc, page) for page in page_numbers]
    finally:
        doc.close()


def clean_whitespace(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
