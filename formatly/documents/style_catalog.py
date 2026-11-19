"""Bounded paragraph-style choices and their actual visible document samples."""
from __future__ import annotations

from typing import Any

from ..files import NS, W
from .docx_semantics import paragraph_style, read_docx_content


def paragraph_style_catalog(package: dict[str, Any], query: str = "", offset: int = 0,
                            limit: int = 20) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > 120:
        raise ValueError("样式搜索最多120字符")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("样式分页参数无效")
    styles = package.get("styles")
    indexed: dict[str, dict[str, Any]] = {}
    if styles is not None:
        for style in styles.findall("w:style", NS):
            identity = style.get(W + "styleId", "")
            if style.get(W + "type") != "paragraph" or not identity or len(identity) > 120:
                continue
            name = style.find("w:name", NS)
            parent = style.find("w:basedOn", NS)
            label = (name.get(W + "val") if name is not None else identity) or identity
            parent_id = parent.get(W + "val", "") if parent is not None else ""
            indexed[identity] = {"id": identity, "name": label[:200],
                                 "based_on": parent_id[:120] or None,
                                 "declared": True, "paragraph_count": 0, "samples": []}
    content = read_docx_content(package["document"], styles, numbering=package.get("numbering"),
                                styles_reason=package.get("styles_reason", ""))
    for paragraph in content.paragraphs:
        if not paragraph.text.strip():
            continue
        identity = paragraph_style(paragraph.element, styles)
        if not identity or len(identity) > 120:
            continue
        if identity not in indexed:
            indexed[identity] = {"id": identity, "name": identity, "based_on": None,
                                 "declared": False, "paragraph_count": 0, "samples": []}
        item = indexed[identity]
        item["paragraph_count"] += 1
        if paragraph.text.strip() and len(item["samples"]) < 3:
            item["samples"].append({"text": paragraph.text.strip()[:200], "location": f"XML段{paragraph.index}"})
    needle = query.strip().casefold()
    matches = [item for item in indexed.values() if not needle or needle in (item["id"] + " " + item["name"] + " "
                + " ".join(sample["text"] for sample in item["samples"])).casefold()]
    matches.sort(key=lambda entry: (-bool(entry["paragraph_count"]), entry["name"].casefold(), entry["id"]))
    return {"items": matches[offset:offset + limit], "total": len(matches), "offset": offset, "limit": limit}
