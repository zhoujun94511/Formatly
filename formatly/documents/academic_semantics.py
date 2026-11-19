"""Observable academic paragraph and section properties in a DOCX package."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from xml.etree.ElementTree import Element

from ..files import NS, W
from .docx_numbering import UNRESOLVED_NUMBERING
from .docx_semantics import DocxParagraph, docx_measure, on_off, paragraph_properties, paragraph_style


@dataclass(frozen=True)
class Observation:
    value: Any = None
    reason: str = ""


def heading_level(paragraph: DocxParagraph, styles: Element | None) -> int | None:
    """Resolve outline levels or an explicit built-in Heading style ancestry."""
    if W + "outlineLvl" in paragraph.property_uncertainty.get("pPr", set()):
        return None
    properties = paragraph_properties(paragraph, styles)
    outline = properties.get(W + "outlineLvl")
    raw = None if outline is None else outline.get(W + "val")
    # An unreadable numbering part must not erase a heading style's identity.
    if raw == UNRESOLVED_NUMBERING:
        raw = None
    if raw is not None:
        # Level 9 explicitly removes the outline role, including on Heading1.
        return int(raw) + 1 if raw in {str(level) for level in range(9)} else None
    indexed = {} if styles is None else {node.get(W + "styleId"): node for node in styles.findall("w:style", NS)}
    identity: str | None = paragraph_style(paragraph.element, styles)
    seen: set[str] = set()
    while identity and identity not in seen:
        seen.add(identity)
        node = indexed.get(identity)
        labels = ["".join(identity.split()).casefold()]
        name = node.find("w:name", NS) if node is not None else None
        if name is not None:
            labels.append("".join(name.get(W + "val", "").split()).casefold())
        # The same styleId or display name that body scope treats as a heading.
        for label in labels:
            match = re.fullmatch(r"(?:heading|标题)([1-9])", label)
            if match and identity in indexed:
                return int(match[1])
        parent = node.find("w:basedOn", NS) if node is not None else None
        identity = parent.get(W + "val") if parent is not None else None
    return None


def paragraph_observation(paragraph: DocxParagraph, styles: Element | None, property_name: str) -> Observation:
    observation = _paragraph_observation(paragraph, styles, property_name)
    if observation.value is None and paragraph.styles_reason:
        return Observation(reason="样式依据无法确认：" + paragraph.styles_reason)
    if observation.value is None and paragraph.numbering_reason:
        return Observation(reason="编号级段落属性无法确认：" + paragraph.numbering_reason)
    return observation


def _paragraph_observation(paragraph: DocxParagraph, styles: Element | None, property_name: str) -> Observation:
    tag = "ind" if property_name == "first_line_indent_chars" else "jc" if property_name == "alignment" else "spacing"
    if W + tag in paragraph.property_uncertainty.get("pPr", set()):
        return Observation(reason="表格条件样式影响该属性，须在排版应用中核对")
    if property_name == "alignment" and W + "bidi" in paragraph.property_uncertainty.get("pPr", set()):
        return Observation(reason="表格条件样式影响文字方向，须在排版应用中核对")
    properties = paragraph_properties(paragraph, styles)
    attrs = properties.get(W + tag, {})
    if property_name == "first_line_indent_chars":
        # Hanging indentation takes precedence over first-line indentation.
        for attribute, sign, characters in (("hangingChars", -1, True), ("hanging", -1, False),
                                             ("firstLineChars", 1, True), ("firstLine", 1, False)):
            if W + attribute in attrs:
                value = docx_measure(attrs[W + attribute], allow_zero=True)
                if characters:
                    return Observation(sign * value / 100) if value is not None else Observation(reason="字符缩进值无效")
                if value == 0:
                    return Observation(0.0)
                return Observation(reason="缩进使用长度单位，无法据此确定字符数")
        return Observation(0.0)
    if property_name in {"before_lines", "after_lines"}:
        side = property_name.removesuffix("_lines")
        automatic = attrs.get(W + side + "Autospacing", "0").strip().lower()
        if automatic not in {"0", "false", "off"}:
            return Observation(reason="自动段距须在排版应用中核对")
        if W + side + "Lines" in attrs:
            value = docx_measure(attrs[W + side + "Lines"], allow_zero=True)
            return Observation(value / 100) if value is not None else Observation(reason="段距行数无效")
        if W + side in attrs:
            value = docx_measure(attrs[W + side], allow_zero=True)
            if value != 0:
                return Observation(reason="段距使用长度单位，无法据此确定行数")
        return Observation(0.0)
    if property_name == "line_spacing_pt":
        raw_rule = attrs.get(W + "lineRule", "auto")
        value = docx_measure(attrs.get(W + "line"))
        if value is None:
            return Observation(reason="未解析到明确的行距值")
        if raw_rule == "exact":
            return Observation(value / 20)
        if raw_rule == "auto":
            return Observation({"mode": "multiple", "value": value / 240})
        if raw_rule == "atLeast":
            return Observation({"mode": "atLeast", "value": value / 20})
        return Observation(reason="行距模式无效")
    if property_name == "alignment":
        alignment = attrs.get(W + "val", "start")
        if alignment in {"left", "center", "right", "both", "distribute", "numTab", "highKashida", "mediumKashida", "lowKashida"}:
            return Observation(alignment)
        if alignment in {"start", "end"}:
            direction = on_off(properties, "bidi")
            if direction is not None:
                return Observation("right" if direction == (alignment == "start") else "left")
        return Observation(reason="段落对齐方式或文字方向无法确定")
    return Observation(reason="该段落属性尚未配置解析")


def section_observation(section: Element, property_name: str) -> Observation:
    if property_name == "columns":
        columns = section.find("w:cols", NS)
        if columns is None:
            return Observation(1)
        raw_count = columns.get(W + "num", "1")
        count = docx_measure(raw_count, maximum=64)
        equal = columns.get(W + "equalWidth", "1").lower()
        if count is None or equal not in {"true", "1", "on", "false", "0", "off"}:
            return Observation(reason="分栏数量或等宽设置无效")
        children = columns.findall("w:col", NS)
        if equal in {"false", "0", "off"} and len(children) != count:
            return Observation(reason="非等宽分栏数量与逐栏设置不一致")
        return Observation(count)
    attribute = {"gutter_mm": "gutter", "header_distance_mm": "header", "footer_distance_mm": "footer"}.get(property_name)
    margins = section.find("w:pgMar", NS)
    if attribute is None or margins is None:
        return Observation(reason="没有明确的分节页边距设置")
    value = docx_measure(margins.get(W + attribute), allow_zero=True, maximum=31680)
    if value is None:
        return Observation(reason="未解析到明确的分节距离")
    return Observation(round(value * 25.4 / 1440, 3))
