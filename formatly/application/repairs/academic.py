"""Safe, explicitly represented writes for native academic format targets."""
from __future__ import annotations

from ...files import W
from ...plugins.academic_rules import ACADEMIC_TARGETS, validate_academic_value


def academic_action(candidate: dict) -> tuple[list[str], dict[str, str]]:
    target, expected = candidate.get("target"), candidate.get("expected")
    if not isinstance(target, str) or target not in ACADEMIC_TARGETS:
        raise ValueError("不支持的论文排版修复项目")
    validate_academic_value(target, expected)
    locator = candidate.get("locator")
    if not isinstance(locator, dict):
        raise ValueError("论文排版修复缺少明确定位")
    owner_tag = locator.get("tag")
    property_name = target.rsplit(".", 1)[-1]
    if target.startswith("headings.") and ".fonts." in target:
        if not isinstance(expected, str):
            raise ValueError("标题字体要求须为字体名称")
        if owner_tag != W + "r" or locator.get("font_slot") != property_name:
            raise ValueError("标题字体缺少匹配的文字类型定位")
        if any(ord(character) < 32 or 0xd800 <= ord(character) <= 0xdfff or ord(character) & 0xffff in {0xfffe, 0xffff}
               for character in expected):
            raise ValueError("标题字体名称含无效 XML 字符")
        return ["rPr", "rFonts"], {property_name: expected}
    if property_name == "alignment":
        if owner_tag != W + "p" or not isinstance(expected, str):
            raise ValueError("标题对齐缺少明确段落或对齐值")
        return ["pPr", "jc"], {"val": expected}
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        raise ValueError("论文排版数值要求无效")
    if target.startswith("section."):
        if target == "section.columns":
            raise ValueError("分栏修改涉及逐栏宽度和页面布局，须在 Word/WPS 中修改")
        if owner_tag != W + "sectPr":
            raise ValueError("分节距离缺少活动分节定位")
        attribute = {"gutter_mm": "gutter", "header_distance_mm": "header", "footer_distance_mm": "footer"}[property_name]
        twips = round(expected * 1440 / 25.4)
        if abs(twips * 25.4 / 1440 - expected) > .05:
            raise ValueError("分节距离要求无法以 DOCX 单位准确表示")
        return ["pgMar"], {attribute: str(twips)}
    if property_name == "size_pt":
        if owner_tag != W + "r" or expected * 2 != round(expected * 2):
            raise ValueError("标题字号须能以 DOCX 的半磅单位准确表示")
        return ["rPr", "sz"], {"val": str(round(expected * 2))}
    if owner_tag != W + "p":
        raise ValueError("段落排版缺少明确的段落定位")
    if property_name == "first_line_indent_chars":
        characters = round(expected * 100)
        if abs(expected * 100 - characters) > 1e-8:
            raise ValueError("首行缩进须能以 DOCX 的百分之一字符准确表示")
        return ["pPr", "ind"], {"firstLineChars": str(characters)}
    if property_name in {"before_lines", "after_lines"}:
        lines = round(expected * 100)
        if abs(expected * 100 - lines) > 1e-8:
            raise ValueError("段距须能以 DOCX 的百分之一行准确表示")
        side = property_name.removesuffix("_lines")
        return ["pPr", "spacing"], {side + "Lines": str(lines), side + "Autospacing": "0"}
    if property_name == "line_spacing_pt":
        twips = round(expected * 20)
        if twips < 1 or abs(twips / 20 - expected) > .01:
            raise ValueError("固定行距须能以 DOCX 的二十分之一磅准确表示")
        return ["pPr", "spacing"], {"line": str(twips), "lineRule": "exact"}
    raise ValueError("此论文排版属性暂不支持自动修复")
