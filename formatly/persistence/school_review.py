"""Choose an actual source excerpt without inventing pagination or locations."""
from __future__ import annotations

import re
from typing import Any


def source_context(text: str, entries: list[dict[str, Any]], locator: str = "", excerpt: str = "") -> dict[str, Any]:
    if not isinstance(locator, str) or len(locator) > 300 or not isinstance(excerpt, str) or len(excerpt) > 2000:
        raise ValueError("来源定位或摘录超长")
    anchor = excerpt.strip()
    paragraphs = set(re.findall(r"XML段(\d{1,8})(?!\d)", locator))
    matches = [index for index, item in enumerate(entries) if (
        len(paragraphs) == 1 and str(item.get("docx_paragraph")) in paragraphs) or (
        locator and isinstance(item.get("location"), str) and item["location"] == locator)]
    if len(matches) == 1:
        entry = entries[matches[0]]
        entry_text = entry.get("text", "")
        position = entry_text.find(anchor) if anchor else -1
        start = max(0, position - 400) if position >= 0 else 0
        end = position + len(anchor) + 800 if position >= 0 else 2400
        return {"location": entry.get("location", "来源提取文本"), "text": entry_text[start:end],
                "matched_excerpt": anchor if position >= 0 else "", "match_found": position >= 0,
                "truncated": start > 0 or end < len(entry_text) or len(entries) > 1}
    fallback = "出处定位不唯一" if len(matches) > 1 or len(paragraphs) > 1 else "出处定位未匹配" if locator else "未提供出处定位"
    position = text.find(anchor) if anchor else -1
    if position >= 0:
        start = max(0, position - 400)
        return {"location": "来源提取文本（" + fallback + "，按摘录首次匹配）", "text": text[start:min(len(text), position + len(anchor) + 800)],
                "matched_excerpt": anchor, "match_found": True, "truncated": start > 0 or position + len(anchor) + 800 < len(text)}
    return {"location": "来源提取文本开头（" + fallback + "）", "text": text[:2400], "matched_excerpt": "", "match_found": False,
            "truncated": len(text) > 2400}
