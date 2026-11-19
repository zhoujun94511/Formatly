"""Public parameters for native DOCX paragraph, heading and section checks."""
from __future__ import annotations

from copy import deepcopy
import math
import re

PARAGRAPH_PROPERTIES = ("first_line_indent_chars", "before_lines", "after_lines", "line_spacing_pt")
FONT_SLOTS = ("eastAsia", "ascii", "hAnsi", "cs")
_FONT_SLOT_LABELS = {"eastAsia": "中文字体", "ascii": "西文字体", "hAnsi": "其他西文字体", "cs": "复杂文字字体"}
ALIGNMENTS = {"left": "左对齐", "center": "居中", "right": "右对齐", "both": "两端对齐"}
_PARAGRAPH_LABELS = {"first_line_indent_chars": "正文首行缩进", "before_lines": "正文段前间距",
                     "after_lines": "正文段后间距", "line_spacing_pt": "正文固定行距"}
_HEADING_LABELS = {"size_pt": "字号", "alignment": "对齐", "before_lines": "段前间距", "after_lines": "段后间距"}
_SECTION_LABELS = {"gutter_mm": "装订线", "header_distance_mm": "页眉距边界", "footer_distance_mm": "页脚距边界", "columns": "分栏数"}
TARGET_LABELS = {"paragraph." + key: label for key, label in _PARAGRAPH_LABELS.items()}
TARGET_LABELS.update({"section." + key: label for key, label in _SECTION_LABELS.items()})
for _level in range(1, 10):
    TARGET_LABELS.update({f"headings.{_level}.{key}": f"{_level}级标题{label}" for key, label in _HEADING_LABELS.items()})
    TARGET_LABELS.update({f"headings.{_level}.fonts.{slot}": f"{_level}级标题" + _FONT_SLOT_LABELS[slot] for slot in FONT_SLOTS})
ACADEMIC_TARGETS = frozenset(TARGET_LABELS)
# Minimum, maximum, exclusive minimum, integer-only.
NUMERIC_TARGETS = {target: (0, 200, target.endswith(("size_pt", "line_spacing_pt")), False)
                   for target in ACADEMIC_TARGETS if not target.endswith("alignment") and ".fonts." not in target}
NUMERIC_TARGETS["section.columns"] = (1, 64, False, True)


def normalize_style_ids(value: object, label: str) -> list[str]:
    if (not isinstance(value, list) or len(value) > 100
            or any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in value)):
        raise ValueError(label + "须为最多100项非空样式ID组成的数组")
    return sorted({item.strip() for item in value})


def validate_academic_value(target: str, value: object) -> None:
    if target not in ACADEMIC_TARGETS:
        raise ValueError("不支持的排版参数：" + target)
    if target in NUMERIC_TARGETS:
        minimum, maximum, exclusive, integer = NUMERIC_TARGETS[target]
        if (not isinstance(value, (int, float)) or isinstance(value, bool) or (integer and type(value) is not int)
                or not (minimum < value if exclusive else minimum <= value) or value > maximum or not math.isfinite(value)):
            raise ValueError(target + f"须为{'大于' if exclusive else '不小于'}{minimum}且不超过{maximum}的" + ("整数" if integer else "数字"))
    elif target.endswith("alignment"):
        if not isinstance(value, str) or value not in ALIGNMENTS:
            raise ValueError(target + "仅支持left/center/right/both")
    elif not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(target + "须为最多120字符的非空字体名称")


def configured_academic_values(settings: dict):
    """Yield canonical leaf targets without exposing scope configuration as checks."""
    for group in ("paragraph", "section"):
        for key, value in settings.get(group, {}).items():
            if group + "." + key in ACADEMIC_TARGETS:
                yield group + "." + key, value
    for level, rules in settings.get("headings", {}).items():
        for key, value in rules.items():
            if key == "fonts":
                for slot, font in value.items():
                    yield f"headings.{level}.fonts.{slot}", font
            else:
                yield f"headings.{level}.{key}", value


def validate_academic_settings(settings: dict) -> None:
    paragraph, headings, section = (settings.get(key, {}) for key in ("paragraph", "headings", "section"))
    if any(not isinstance(group, dict) for group in (paragraph, headings, section)):
        raise ValueError("paragraph、headings和section须为对象")
    if set(paragraph) - {*PARAGRAPH_PROPERTIES, "style_ids", "property_style_ids"}:
        raise ValueError("paragraph包含不支持的参数")
    if set(section) - set(_SECTION_LABELS):
        raise ValueError("section包含不支持的参数")
    if "style_ids" in paragraph:
        normalize_style_ids(paragraph["style_ids"], "paragraph.style_ids")
    scopes = paragraph.get("property_style_ids", {})
    if not isinstance(scopes, dict) or set(scopes) - set(PARAGRAPH_PROPERTIES):
        raise ValueError("paragraph.property_style_ids包含不支持的段落属性")
    for key, scope in scopes.items():
        normalize_style_ids(scope, "paragraph.property_style_ids." + key)
    if set(headings) - {str(level) for level in range(1, 10)}:
        raise ValueError("headings仅支持1至9级标题")
    for level, rules in headings.items():
        if not isinstance(rules, dict) or set(rules) - {*_HEADING_LABELS, "fonts"}:
            raise ValueError("headings." + level + "包含不支持的参数")
        fonts = rules.get("fonts", {})
        if not isinstance(fonts, dict) or set(fonts) - set(FONT_SLOTS):
            raise ValueError("标题字体仅支持eastAsia/ascii/hAnsi/cs")
    for target, value in configured_academic_values(settings):
        validate_academic_value(target, value)
    body = settings.get("body", {})
    if "line_spacing_pt" in paragraph and isinstance(body, dict) and "line_spacing" in body:
        body_scopes = body.get("property_style_ids", {})
        if not isinstance(body_scopes, dict):
            raise ValueError("body.property_style_ids须为对象")
        fixed_scope = set(normalize_style_ids(scopes.get("line_spacing_pt", paragraph.get("style_ids", [])), "固定行距样式范围"))
        multiple_scope = set(normalize_style_ids(body_scopes.get("line_spacing", body.get("style_ids", [])), "倍数行距样式范围"))
        if not fixed_scope or not multiple_scope or fixed_scope & multiple_scope:
            raise ValueError("同一或未明确的正文样式范围不能同时设置固定磅数行距和倍数行距")


def academic_fields() -> list[dict]:
    fields: list[dict] = [{"path": "paragraph.style_ids", "label": "正文段落样式范围", "group": "正文段落", "type": "lines",
               "placeholder": "每行一个文档样式 ID", "help": "须明确正文样式范围；留空时段落要求保留人工复核。"}]
    for target, label in TARGET_LABELS.items():
        if target.startswith("headings.") and int(target.split(".")[1]) > 3:
            continue
        group = "正文段落" if target.startswith("paragraph.") else "分节版式" if target.startswith("section.") else target.split(".")[1] + "级标题"
        field: dict = {"path": target, "label": label, "group": group, "type": "number" if target in NUMERIC_TARGETS else "text"}
        if target in NUMERIC_TARGETS:
            minimum, maximum, exclusive, integer = NUMERIC_TARGETS[target]
            field["exclusiveMinimum" if exclusive else "minimum"] = minimum
            field["maximum"] = maximum
            if integer:
                field["integer"] = True
            field["unit"] = "字符" if target.endswith("indent_chars") else "磅" if target.endswith(("size_pt", "spacing_pt")) else "毫米" if target.endswith("_mm") else "栏" if target.endswith("columns") else "行"
        elif target.endswith("alignment"):
            field.update(type="select", options=[{"value": value, "label": text} for value, text in ALIGNMENTS.items()])
        fields.append(field)
    return deepcopy(fields)


def academic_value_schema(target: str) -> dict:
    if target in NUMERIC_TARGETS:
        minimum, maximum, exclusive, integer = NUMERIC_TARGETS[target]
        return {"type": "integer" if integer else "number", "exclusiveMinimum" if exclusive else "minimum": minimum, "maximum": maximum}
    if target.endswith("alignment"):
        return {"enum": list(ALIGNMENTS)}
    return {"type": "string", "pattern": r"\S", "maxLength": 120}


def academic_settings_schema(style_ids_schema: dict) -> dict:
    def group(properties):
        return {"type": "object", "properties": properties, "additionalProperties": False}
    heading = {key: academic_value_schema("headings.1." + key) for key in _HEADING_LABELS}
    heading["fonts"] = group({slot: academic_value_schema("headings.1.fonts." + slot) for slot in FONT_SLOTS})
    return {
        "paragraph": group({**{key: academic_value_schema("paragraph." + key) for key in PARAGRAPH_PROPERTIES},
                            "style_ids": deepcopy(style_ids_schema),
                            "property_style_ids": group({key: deepcopy(style_ids_schema) for key in PARAGRAPH_PROPERTIES})}),
        "headings": group({str(level): group(deepcopy(heading)) for level in range(1, 10)}),
        "section": group({key: academic_value_schema("section." + key) for key in _SECTION_LABELS}),
    }


def academic_text_values(line: str, body_parts: list[str]) -> list[tuple[str, object, str]]:
    """Extract explicitly named attributes only; retain other clauses for review."""
    result = []
    number = r"(\d+(?:\.\d+)?)"
    for part in body_parts:
        if re.search(r"不(?:[要应得]|采用|使用|设置)|无需|不要求|禁止", part):
            continue
        for key, pattern in (("first_line_indent_chars", rf"首行缩进\s*[为：:]?\s*{number}\s*(?:字符|字)"),
                             ("before_lines", rf"段前(?:间距|距)?\s*[为：:]?\s*{number}\s*行"),
                             ("after_lines", rf"段后(?:间距|距)?\s*[为：:]?\s*{number}\s*行"),
                             ("line_spacing_pt", rf"(?:行距\s*[为：:]?\s*)?固定值?\s*{number}\s*(?:磅|pt)")):
            match = re.search(pattern, part, re.I)
            if match:
                result.append(("paragraph." + key, float(match[1]), _PARAGRAPH_LABELS[key] + "候选"))
    for key, phrase in (("gutter_mm", "装订线"), ("header_distance_mm", "页眉距离?边[界缘]"),
                        ("footer_distance_mm", "页脚距离?边[界缘]")):
        for match in re.finditer(phrase + rf"\s*[为：:]?\s*{number}\s*(毫米|mm|厘米|cm)", line, re.I):
            if re.search(r"不(?:[要应得]|采用|使用|设置)|无需|不要求|禁止", _clause_segment(line, match.start(), match.end())):
                continue
            result.append(("section." + key, float(match[1]) * (10 if match[2].lower() in {"厘米", "cm"} else 1), _SECTION_LABELS[key] + "候选"))
            break
    for columns in re.finditer(r"分栏数?\s*[为：:]?\s*([1-9]\d?)\s*栏|(?:单栏|双栏)(?:版式|排版)?", line):
        segment = _clause_segment(line, columns.start(), columns.end())
        if re.search(r"不(?:是|能|[要应得]|采用|使用|设置)|无需|不要求|禁止|非单栏|或者|或|可以|附录|除外|除非|可(?!见)", segment):
            continue
        column_count = int(columns[1]) if columns[1] else 2 if columns[0].startswith("双") else 1
        result.append(("section.columns", column_count, "分栏数候选"))
        break
    for heading in re.finditer(r"([一二三四五六七八九1-9])级标题", line):
        level = str("一二三四五六七八九".index(heading[1]) + 1) if heading[1] in "一二三四五六七八九" else heading[1]
        text = line[heading.end():]
        # A shared “与正文均使用” phrase keeps this heading's attributes, then stops
        # at the next heading so that heading's size is not copied backward.
        next_heading = re.search(r"[一二三四五六七八九1-9]级标题|页眉|页脚", text)
        shared = re.search(r"与正文(?:均|都|一并|同时)?(?:使用|采用|用)", text)
        if shared and (next_heading is None or shared.start() < next_heading.start()):
            text = text[:next_heading.start()] if next_heading else text
        else:
            text = re.split(r"[一二三四五六七八九1-9]级标题|正文|页眉|页脚", text, maxsplit=1)[0]
        if re.search(r"不(?:[要应得]|采用|使用|设置)|无需|不要求|禁止", text):
            continue
        font = re.search(r"黑体|宋体|仿宋|楷体|Times New Roman|Arial", text, re.I)
        if font:
            slot = "ascii" if re.search(r"[A-Za-z]", font[0]) else "eastAsia"
            result.append((f"headings.{level}.fonts.{slot}", font[0], level + "级标题字体候选"))
        size = re.search(r"字号\s*[为：:]?\s*" + number + r"\s*(?:磅|pt)", text, re.I)
        if size is None and font:
            size = re.match(r"\s*[,，]?\s*" + number + r"\s*(?:磅|pt)", text[font.end():], re.I)
        before_font = text[:font.start()] if font else ""
        if size is None and font and not re.search(r"段前|段后|行距|固定值?", before_font):
            size = re.search(r"(?:^|[\s,，、])" + number + r"\s*(?:磅|pt)\s*(?:[,，、]\s*)?$", before_font, re.I)
        if size:
            result.append((f"headings.{level}.size_pt", float(size[1]), level + "级标题字号候选"))
        else:
            named = re.search(r"小四|小三|小二|小一|四号|三号|二号|一号|五号|小五", text)
            sizes = {"小四": 12, "小三": 15, "小二": 18, "小一": 24, "四号": 14, "三号": 16, "二号": 22, "一号": 26, "五号": 10.5, "小五": 9}
            if named:
                result.append((f"headings.{level}.size_pt", sizes[named[0]], level + "级标题字号候选"))
        alignment = next((value for phrase, value in (("两端对齐", "both"), ("左对齐", "left"), ("右对齐", "right"), ("居中", "center")) if phrase in text), None)
        if alignment:
            result.append((f"headings.{level}.alignment", alignment, level + "级标题对齐候选"))
        for key, phrase in (("before_lines", "段前"), ("after_lines", "段后")):
            match = re.search(phrase + rf"(?:间距|距)?\s*[为：:]?\s*{number}\s*行", text)
            if match:
                result.append((f"headings.{level}.{key}", float(match[1]), level + "级标题间距候选"))
    return [(target, value, label) for target, value, label in result
            if target not in NUMERIC_TARGETS or _valid_number(target, value)]


def _clause_segment(line: str, start: int, end: int) -> str:
    """Keep a prohibition or an optional wording inside the clause that states it."""
    marks = "，,；;。"
    left = max(line.rfind(mark, 0, start) for mark in marks)
    right = len(line)
    for mark in marks:
        found = line.find(mark, end)
        if found != -1:
            right = min(right, found)
    return line[left + 1:right]


def _valid_number(target: str, value: object) -> bool:
    try:
        validate_academic_value(target, value)
        return True
    except ValueError:
        return False
