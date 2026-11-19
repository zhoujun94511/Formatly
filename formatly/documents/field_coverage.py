"""Whether visible text is a sufficient search scope for a labelled form."""
from __future__ import annotations

import re

from ..files import W


def field_text_coverage(document: dict) -> dict:
    """Keep successful extraction separate from proof of a missing field.

    A native text layer can coexist with pictures, outlined text or document
    parts that this reader does not interpret. Such inputs remain reviewable.
    """
    reasons = []
    if document.get("complete"):
        reasons.append("extraction_incomplete")
    if document.get("requires_review") is not False:
        reasons.append("extraction_requires_review")
    if "\ufffd" in document.get("text", ""):
        reasons.append("unverified_characters")
    entries = document.get("entries", [])
    if any(entry.get("method") != "text" or (
            isinstance(entry.get("confidence"), (int, float)) and entry["confidence"] < 80)
           for entry in entries):
        reasons.append("non_native_or_uncertain_text")
    kind = document.get("format")
    if kind == "docx":
        package = document.get("docx") or {}
        xml = package.get("document")
        parts = package.get("parts")
        if xml is None or not isinstance(parts, list) or "word/document.xml" not in parts:
            reasons.append("docx_scope_unverified")
        if xml is not None:
            unsupported = {W + name for name in (
                "drawing", "pict", "object", "txbxContent", "altChunk", "sym", "fldSimple", "instrText")}
            if any(node.tag in unsupported or node.tag.startswith(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/math}") for node in xml.iter()):
                reasons.append("docx_non_text_content")
        if any(re.match(r"word/(?:header\d*|footer\d*|footnotes|endnotes)\.xml$", part)
               or part.startswith(("word/media/", "word/embeddings/")) for part in parts or []):
            reasons.append("docx_unread_parts")
    elif kind == "pdf":
        pages = document.get("pages") or []
        if (not pages or document.get("page_count") != len(pages)
                or document.get("processed_pages") != len(pages)):
            reasons.append("pdf_page_scope_unverified")
        if any(page.get("method") != "text" or page.get("non_text_objects") != 0
               or page.get("hidden_characters") != 0 or page.get("unverified_characters") != 0
               or bool(page.get("auxiliary_text")) for page in pages):
            reasons.append("pdf_non_native_or_graphical_content")
    elif kind == "md":
        if re.search(r"!\[|<\s*[A-Za-z/!]|^\s*(?:```|~~~)", document.get("text", ""), re.MULTILINE):
            reasons.append("markdown_embedded_or_code_content")
    elif kind == "json":
        if document.get("json_schema") != "formatly.document.v1":
            reasons.append("json_text_scope_undeclared")
    elif kind != "txt":
        reasons.append("text_scope_unsupported")
    return {"complete": not reasons, "scope": "document_text", "reasons": reasons}
