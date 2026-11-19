"""Document readers and DOCX/PDF semantic helpers."""

from .reader import (
    MAX_FILE_BYTES,
    MAX_OCR_PAGES,
    MAX_PDF_PAGES,
    MAX_TEXT_BYTES,
    document_format,
    docx_entries,
    probe_ocr,
    probe_pdf,
    read_document,
)

__all__ = [
    "MAX_FILE_BYTES",
    "MAX_OCR_PAGES",
    "MAX_PDF_PAGES",
    "MAX_TEXT_BYTES",
    "document_format",
    "docx_entries",
    "probe_ocr",
    "probe_pdf",
    "read_document",
]
