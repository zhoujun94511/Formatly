"""Compare observable font family names while retaining raw evidence elsewhere."""
from __future__ import annotations

import re

FONT_ALIASES = {"宋体": "simsun", "黑体": "simhei", "楷体": "kaiti", "仿宋": "fangsong"}
FONT_FAMILIES = ("timesnewroman", "arial", "calibri", "simsun", "simhei", "kaiti", "fangsong")
FONT_SUFFIXES = ("", "psmt", "psboldmt", "psitalicmt", "psbolditalicmt", "bold", "italic", "bolditalic")


def is_font_target(target: str) -> bool:
    return target == "body.font" or target.startswith("body.fonts.") or target.startswith("headings.") and ".fonts." in target


def font_comparison_rules() -> dict:
    """Publish the same family aliases used by the document detectors."""
    return {"kind": "font_family", "aliases": dict(FONT_ALIASES), "families": list(FONT_FAMILIES), "suffixes": list(FONT_SUFFIXES)}


def normalize_font_name(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if value.strip().casefold() == "unknown":
        return None
    value = re.sub(r"^[A-Z]{6}\+", "", value)
    value = re.sub(r"[\s,_-]", "", value).casefold()
    if re.fullmatch(r"(?:f|font|cidfont)\d+", value):
        return None
    value = FONT_ALIASES.get(value, value)
    for family in FONT_FAMILIES:
        if value in {family + suffix for suffix in FONT_SUFFIXES}:
            return family
    return value
