"""Shared effective DOCX properties and conservative, visible content traversal."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from xml.etree.ElementTree import Element

from ..files import NS, W
from .docx_numbering import NumberingContext, UNRESOLVED_NUMBERING, paragraph_numbering
from .ooxml import parse_on_off

MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_ON_OFF = {W + name for name in ("vanish", "webHidden", "specVanish", "cs", "rtl")}
# Print and preview still show webHidden text. Vanish and specVanish stay excluded.
_HIDDEN = ("vanish", "specVanish")
_DELETED = {W + "del", W + "moveFrom", W + "delText"}
_MOVE_RANGES = {W + name for name in ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")}
_UNKNOWN_PARAGRAPH = {
    "ind": ("hangingChars", "hanging", "firstLineChars", "firstLine"),
    "spacing": ("beforeAutospacing", "beforeLines", "before", "afterAutospacing", "afterLines", "after", "line", "lineRule"),
    **{name: ("val",) for name in ("jc", "bidi", "outlineLvl", "pageBreakBefore")},
}


def _unknown_properties(tag: str) -> dict:
    attributes = _UNKNOWN_PARAGRAPH if tag == "pPr" else {
        "rFonts": tuple(slot for name in ("ascii", "hAnsi", "eastAsia", "cs") for slot in (name, name + "Theme")),
        **{name: ("val",) for name in ("sz", "szCs", "cs", "rtl", "vanish", "webHidden", "specVanish")},
    }
    return {W + name: {W + attr: "unresolved_styles" for attr in attrs} for name, attrs in attributes.items()}


def on_off(properties: dict, name: str) -> bool | None:
    value = properties.get(W + name)
    if value is None:
        return False
    return parse_on_off(value.get(W + "val"), default=True)


def _merge(properties: dict, child: Element, *, style=False) -> None:
    if style and child.tag in {W + name for name in _HIDDEN}:
        enabled = parse_on_off(child.get(W + "val"), default=True)
        if enabled is False:
            return
        previous = on_off(properties, child.tag.removeprefix(W))
        properties[child.tag] = {W + "val": "invalid" if previous is None or enabled is None
                                else "false" if previous else "true"}
        return
    if child.tag in _ON_OFF:
        properties[child.tag] = {W + "val": child.get(W + "val", "true")}
    else:
        properties.setdefault(child.tag, {}).update(child.attrib)


def merged_properties(styles, style_id, tag, include_defaults=True, *, initial=None, styles_reason=""):
    """Resolve document defaults and the explicit basedOn chain."""
    result = {key: dict(value) for key, value in (initial or {}).items()}
    if styles_reason and include_defaults:
        result = _unknown_properties(tag) | result
    if styles is None:
        return result
    default = styles.find(f"w:docDefaults/w:{tag}Default/w:{tag}", NS)
    if include_defaults and default is not None:
        for element in default:
            _merge(result, element)
    indexed = {style.get(W + "styleId"): style for style in styles.findall("w:style", NS)}
    chain, seen = [], set()
    while style_id in indexed and style_id not in seen:
        seen.add(style_id)
        style = indexed[style_id]
        chain.append(style)
        parent = style.find("w:basedOn", NS)
        style_id = parent.get(W + "val") if parent is not None else None
    for style in reversed(chain):
        props = style.find("w:" + tag, NS)
        if props is not None:
            for element in props:
                _merge(result, element, style=True)
    return result


def overlay(properties, element):
    properties = {key: dict(value) for key, value in properties.items()}
    if element is not None:
        for child in element:
            _merge(properties, child)
    return properties


def default_paragraph_style(styles) -> str:
    if styles is not None:
        return next((style.get(W + "styleId", "Normal") for style in styles.findall("w:style", NS)
                     if style.get(W + "type") == "paragraph" and parse_on_off(style.get(W + "default"), default=False) is True), "Normal")
    return "Normal"


def paragraph_style(paragraph: Element, styles) -> str:
    node = paragraph.find("w:pPr/w:pStyle", NS)
    return node.get(W + "val", "") if node is not None else default_paragraph_style(styles)


def paragraph_properties(paragraph: Element | DocxParagraph, styles, *, uncertainty=None,
                         numbering: NumberingContext | None = None, styles_reason="") -> dict:
    if isinstance(paragraph, DocxParagraph):
        if paragraph.effective_properties is not None:
            return {tag: dict(attrs) for tag, attrs in paragraph.effective_properties.items()}
        uncertainty = paragraph.property_uncertainty if uncertainty is None else uncertainty
        styles_reason = paragraph.styles_reason or styles_reason
        paragraph = paragraph.element
    result = merged_properties(styles, paragraph_style(paragraph, styles), "pPr", styles_reason=styles_reason)
    resolved = paragraph_numbering(paragraph, styles, numbering)
    if resolved.reason:
        # Unknown numbered paragraph properties do not affect text-run fonts or
        # sizes. Direct scalar properties and explicit spacing attributes can
        # still override their own unknown values without hiding other gaps.
        for name, attributes in _UNKNOWN_PARAGRAPH.items():
            result.setdefault(W + name, {}).update({W + attr: UNRESOLVED_NUMBERING for attr in attributes})
    else:
        # Word applies the numbering level after the paragraph style. Direct
        # paragraph formatting remains the final layer; attributes inherit
        # independently, including hanging/first-line indentation conflicts.
        result = overlay(result, resolved.properties)
    result = overlay(result, paragraph.find("w:pPr", NS))
    if resolved.reason:
        direct = paragraph.find("w:pPr/w:ind", NS)
        stored = result.get(W + "ind")
        if direct is not None and isinstance(stored, dict):
            concrete = [attr for attr in ("firstLine", "firstLineChars", "hanging", "hangingChars")
                        if direct.get(W + attr) not in (None, "")]
            if concrete:
                for attr in ("firstLine", "firstLineChars", "hanging", "hangingChars"):
                    if attr not in concrete and stored.get(W + attr) == UNRESOLVED_NUMBERING:
                        stored.pop(W + attr, None)
    for name in (uncertainty or {}).get("pPr", set()):
        result[name] = {W + "val": "unresolved_table_style"}
    return result


def table_style_uncertainty(document: Element, styles) -> dict[Element, dict[str, set[str]]]:
    """Identify table-dependent attributes until conditional precedence is known.

    This does not guess a Word/WPS rendering order. Paragraphs retain text and
    locations while only properties a containing table style can affect are
    withheld from automatic typography conclusions.
    """
    indexed = {} if styles is None else {node.get(W + "styleId"): node for node in styles.findall("w:style", NS)}
    default = next((key for key, node in indexed.items()
                    if node.get(W + "type") == "table" and parse_on_off(node.get(W + "default"), default=False) is True), None)
    all_properties = {"rPr": {W + key for key in ("rFonts", "sz", "szCs", "cs", "rtl", *_HIDDEN)},
                      "pPr": {W + "spacing", W + "ind"}}
    cache = {}

    def properties(identity):
        if identity in cache:
            return cache[identity]
        affected = {"rPr": set(), "pPr": set()}
        seen = set()
        while identity is not None:
            if identity in seen or identity not in indexed:
                affected = {kind: set(names) for kind, names in all_properties.items()}
                break
            seen.add(identity)
            node = indexed[identity]
            for kind in affected:
                for owner in node.findall(".//w:" + kind, NS):
                    affected[kind].update(child.tag for child in owner)
            parent = node.find("w:basedOn", NS)
            identity = parent.get(W + "val") if parent is not None else None
        return affected

    result = {}

    def visit(node, inherited):
        if node.tag == W + "tbl":
            style = node.find("w:tblPr/w:tblStyle", NS)
            identity = style.get(W + "val", "") if style is not None else default
            if identity is not None:
                if identity not in cache:
                    cache[identity] = properties(identity)
                affected = cache[identity]
                inherited = {kind: inherited[kind] | affected[kind] for kind in inherited}
        if node.tag == W + "p" and any(inherited.values()):
            result[node] = inherited
        for child in node:
            visit(child, inherited)

    visit(document, {"rPr": set(), "pPr": set()})
    return result


def active_sections(document: Element) -> list[Element]:
    """Read body sections through active block containers, excluding histories.

    A section mark belongs to its containing paragraph. Tables, text boxes,
    property histories and unresolved compatibility branches do not introduce
    body sections. A block content control exposes only its sdtContent.
    """
    body = document.find("w:body", NS)
    result: list[Element] = []

    def visit(container: Element) -> None:
        for node in container:
            if node.tag == W + "p":
                section = node.find("w:pPr/w:sectPr", NS)
                if section is not None:
                    result.append(section)
            elif node.tag == W + "sdt":
                content = node.find("w:sdtContent", NS)
                if content is not None:
                    visit(content)
            elif node.tag in {W + "customXml", W + "ins", W + "moveTo"}:
                visit(node)
            elif container is body and node.tag == W + "sectPr":
                result.append(node)

    if body is not None:
        visit(body)
    return result


def _nonnegative_integer(raw: str | None) -> int | None:
    if raw is None or len(raw) > 12 or re.fullmatch(r"\+?[0-9]+", raw.strip()) is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 2_147_483_647 else None


def docx_measure(raw: str | None, *, allow_zero=False, maximum=2_147_483_647) -> int | None:
    """Read a bounded integer XML measure; malformed/nonfinite values are unknown."""
    if raw is None or len(raw) > 12:
        return None
    value = _nonnegative_integer(raw)
    return value if value is not None and (0 if allow_zero else 1) <= value <= maximum else None


def paragraph_after_lines(paragraph: Element | DocxParagraph, styles, *, uncertainty=None) -> float | None:
    """Resolve effective after-spacing only when it has a known line value."""
    if W + "spacing" in (uncertainty or {}).get("pPr", set()):
        return None
    spacing = paragraph_properties(paragraph, styles).get(W + "spacing", {})
    automatic = spacing.get(W + "afterAutospacing", "0").strip().lower()
    if automatic not in {"0", "false", "off"}:
        # Auto-spacing has precedence over afterLines/after and is application
        # dependent. Invalid flags must not be interpreted as disabled.
        return None
    if W + "afterLines" in spacing:
        lines = _nonnegative_integer(spacing[W + "afterLines"])
        return lines / 100 if lines is not None else None
    if W + "after" in spacing:
        # Non-zero twip spacing needs the application's effective line height.
        return 0.0 if _nonnegative_integer(spacing[W + "after"]) == 0 else None
    return 0.0


def run_properties(styles, paragraph: Element, run: Element, *, uncertainty=None, styles_reason="") -> dict:
    result = merged_properties(styles, paragraph_style(paragraph, styles), "rPr", styles_reason=styles_reason)
    style = run.find("w:rPr/w:rStyle", NS)
    if style is not None:
        result = merged_properties(styles, style.get(W + "val"), "rPr", include_defaults=False, initial=result)
    result = overlay(result, run.find("w:rPr", NS))
    for name in (uncertainty or {}).get("rPr", set()):
        result[name] = {W + "val": "unresolved_table_style"}
    return result


def font_slots(text: str) -> set[str]:
    slots = set()
    for char in text:
        if char.isspace():
            continue
        point = ord(char)
        if (0x2e80 <= point <= 0x9fff or 0xac00 <= point <= 0xd7af or
                0xf900 <= point <= 0xffef or 0x20000 <= point <= 0x323af):
            slots.add("eastAsia")
        elif point < 128:
            slots.add("ascii")
        elif 0x0590 <= point <= 0x0dff:
            slots.add("cs")
        else:
            slots.add("hAnsi")
    return slots


def effective_font_slots(text: str, properties: dict) -> set[str] | None:
    controls = [on_off(properties, name) for name in ("cs", "rtl")]
    if None in controls:
        return None
    if any(controls):
        return {"cs"}
    # Font hint/language can redirect non-ASCII Latin and punctuation. Do not
    # guess those assignments until the complete font-selection table is used.
    fonts = properties.get(W + "rFonts", {})
    hint = fonts.get(W + "hint")
    slots = font_slots(text)
    if hint not in {None, "default"} and "hAnsi" in slots:
        return None
    if ("eastAsia" in slots and fonts.get(W + "eastAsia") == "Times New Roman"
            and fonts.get(W + "ascii") and fonts.get(W + "ascii") == fonts.get(W + "hAnsi")):
        return None
    return slots


def effective_font_name(slot: str, properties: dict) -> str | None:
    fonts = properties.get(W + "rFonts", {})
    if fonts.get(W + slot + "Theme") or (slot == "cs" and fonts.get(W + "cstheme")):
        return None
    return fonts.get(W + slot)


def effective_size_pt(text: str, properties: dict) -> float | None:
    slots = effective_font_slots(text, properties)
    if slots is None:
        return None
    names = ({"szCs"} if slots == {"cs"} else {"sz", "szCs"} if "cs" in slots else {"sz"})
    values = []
    for name in names:
        raw = properties.get(W + name, {}).get(W + "val")
        half_points = docx_measure(raw, maximum=1638)
        if half_points is None:
            return None
        value = half_points / 2
        values.append(value)
    return values[0] if values and all(value == values[0] for value in values) else None


@dataclass
class DocxRun:
    index: int
    element: Element
    text: str
    properties: dict


@dataclass
class DocxParagraph:
    index: int
    element: Element
    text: str
    runs: list[DocxRun] = field(default_factory=list)
    property_uncertainty: dict[str, set[str]] = field(default_factory=dict)
    effective_properties: dict | None = None
    numbering_reason: str = ""
    styles_reason: str = ""


@dataclass
class DocxContent:
    paragraphs: list[DocxParagraph] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def requires_review(self) -> bool:
        return bool(self.warnings)


def reference_hanging(paragraph: DocxParagraph, styles) -> dict:
    """Resolve character-unit precedence and absent indentation consistently."""
    sizes = [effective_size_pt(run.text, run.properties) for run in paragraph.runs if run.text.strip()]
    size_pt = sizes[0] if sizes and all(value == sizes[0] for value in sizes) else None
    if W + "ind" in paragraph.property_uncertainty.get("pPr", set()):
        return {"chars": None, "twips": None, "size_pt": size_pt}
    indent = paragraph_properties(paragraph, styles).get(W + "ind", {})
    if W + "hangingChars" in indent:
        units = _nonnegative_integer(indent[W + "hangingChars"])
        chars = units / 100 if units is not None else None
        twips = chars * size_pt * 20 if chars is not None and size_pt else None
    else:
        raw_hanging = indent.get(W + "hanging")
        if raw_hanging is not None:
            twips = _nonnegative_integer(raw_hanging)
        elif W + "firstLineChars" in indent:
            # A positive first-line indent is not a hanging indent. Malformed
            # character values cannot prove the effective indentation.
            twips = 0 if _nonnegative_integer(indent[W + "firstLineChars"]) is not None else None
        else:
            try:
                raw_first_line = indent.get(W + "firstLine", "0")
                if len(raw_first_line) > 12 or re.fullmatch(r"[+-]?[0-9]+", raw_first_line.strip()) is None:
                    raise ValueError("Invalid signed indentation")
                first_line = int(raw_first_line)
                twips = max(-first_line, 0) if abs(first_line) <= 2_147_483_647 else None
            except (TypeError, ValueError):
                twips = None
        chars = twips / (size_pt * 20) if twips is not None and size_pt else None
    return {"chars": round(chars, 4) if chars is not None else None, "twips": twips, "size_pt": size_pt}


def read_docx_content(document: Element, styles=None, *, numbering: NumberingContext | None = None,
                      styles_reason="") -> DocxContent:
    """Read only visible, active text; leave unresolved branches unconsumed.

    XML paragraph/run indexes remain indexes of the original tree so evidence
    and repair locators do not drift when hidden or inactive nodes are skipped.
    """
    result = DocxContent()
    paragraphs = document.findall(".//w:p", NS)
    paragraph_indexes = {id(node): index for index, node in enumerate(paragraphs, 1)}
    table_uncertainty = table_style_uncertainty(document, styles)

    def warn(message):
        if message not in result.warnings:
            result.warnings.append(message)

    if styles_reason:
        warn("DOCX 样式依据无法确认：" + styles_reason)

    if any(node.tag.startswith(W) and (node.tag.endswith("Change") or node.tag in _MOVE_RANGES)
           for node in document.iter()):
        warn("DOCX 含修订属性或移动范围，须核对最终修订视图")

    def active(node):
        if node.tag == W + "tr" and node.find("w:trPr/w:del", NS) is not None:
            warn("DOCX 含删除表格行修订，已排除该行历史文字，仍须核对最终修订视图")
            return False
        if node.tag == W + "tc" and node.find("w:tcPr/w:cellDel", NS) is not None:
            warn("DOCX 含删除单元格修订，已排除该单元格历史文字，仍须核对最终修订视图")
            return False
        if node.tag == MC + "AlternateContent":
            warn("DOCX 含互斥兼容分支，未将未确认显示的分支用于标题、字段或格式通过判断")
            return False
        if node.tag in _DELETED:
            warn("DOCX 含删除或移出修订，检测排除历史文字，仍须核对最终修订视图")
            return False
        if node.tag in {W + "ins", W + "moveTo"}:
            warn("DOCX 含插入或移入修订，按当前内容读取，仍须核对最终修订视图")
        return True

    def read_paragraph(paragraph):
        pieces, runs = [], []
        uncertainty = table_uncertainty.get(paragraph, {})
        if uncertainty:
            warn("DOCX 表格样式含尚未确认优先级的文字或段落属性，相关格式须在 Word/WPS 中核对")
        indexes = {id(node): index for index, node in enumerate(paragraph.findall(".//w:r", NS), 1)}

        def visit(node):
            if not active(node):
                return
            if node is not paragraph and node.tag == W + "p":
                walk(node)
                return
            if node.tag in {W + "pPr", W + "rPr"}:
                return
            if node.tag == W + "r":
                properties = run_properties(styles, paragraph, node, uncertainty=uncertainty, styles_reason=styles_reason)
                visibility = [on_off(properties, name) for name in _HIDDEN]
                if None in visibility:
                    warn("DOCX 含无法确定的隐藏文字属性，该运行未用于自动核验")
                    return
                if any(visibility):
                    warn("DOCX 含隐藏文字，已排除正常显示中不可见的内容，请核对显示与打印设置")
                    return
                text = []

                def run_text(element):
                    if not active(element):
                        return
                    if element.tag == W + "p":
                        walk(element)
                        return
                    if element.tag == W + "rPr":
                        return
                    if element.tag == W + "t":
                        text.append(element.text or "")
                    elif element.tag == W + "tab":
                        text.append("\t")
                    elif element.tag in {W + "br", W + "cr"}:
                        text.append("\n")
                    else:
                        for nested in element:
                            run_text(nested)

                for child in node:
                    run_text(child)
                value = "".join(text)
                pieces.append(value)
                runs.append(DocxRun(indexes[id(node)], node, value, properties))
                return
            for child in node:
                visit(child)

        visit(paragraph)
        effective = paragraph_properties(paragraph, styles, numbering=numbering, uncertainty=uncertainty, styles_reason=styles_reason)
        resolved = paragraph_numbering(paragraph, styles, numbering)
        result.paragraphs.append(DocxParagraph(paragraph_indexes[id(paragraph)], paragraph, "".join(pieces).strip(), runs,
                                               uncertainty, effective, resolved.reason, styles_reason))

    def walk(node):
        if not active(node):
            return
        if node.tag == W + "p":
            read_paragraph(node)
        else:
            for child in node:
                walk(child)

    walk(document)
    result.paragraphs.sort(key=lambda item: item.index)
    return result
