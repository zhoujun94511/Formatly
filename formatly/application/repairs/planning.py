"""Build snapshot-bound, safe DOCX repair plans."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, TypeGuard
import unicodedata
from xml.etree.ElementTree import Element, tostring

from ...files import NS, W, read_docx, sha256
from ...documents.docx_semantics import (effective_font_name, effective_font_slots, effective_size_pt,
                                        paragraph_after_lines, paragraph_style, read_docx_content,
                                        reference_hanging)
from ...documents.academic_semantics import paragraph_observation, section_observation
from ...plugins.academic_rules import ACADEMIC_TARGETS, TARGET_LABELS
from ...persistence.school_compiler import expected_key, requirement_scope, scope_unresolved
from ..scoped_execution import run_scoped_plugin
from .academic import academic_action
from .safety import _part_safety

MAX_REPAIR_CANDIDATES = 1000
_FONT_SLOTS = {"eastAsia", "ascii", "hAnsi", "cs"}
_LABELS = {"page.width_mm": "纸张宽度（mm）", "page.height_mm": "纸张高度（mm）",
           "page.margins_mm.top": "上页边距（mm）", "page.margins_mm.bottom": "下页边距（mm）",
           "page.margins_mm.left": "左页边距（mm）", "page.margins_mm.right": "右页边距（mm）",
           "body.font": "正文字体", "body.size_pt": "正文字号（pt）", "body.line_spacing": "正文行距（倍）",
           "references.heading_after_lines": "参考文献标题段后距（行）",
           "references.entry_hanging_chars": "参考文献悬挂缩进（字符）"}
_COMPLEX = {W + name for name in ("fldChar", "instrText", "fldSimple", "hyperlink", "drawing", "object",
                                 "pict", "txbxContent", "sdt", "customXml", "subDoc", "altChunk")}
_COMPLEX.add("{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent")
def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

def _plan_digest(plan: dict) -> str:
    return _digest({key: plan[key] for key in ("version", "input_sha256", "profile_sha256", "candidates", "skipped")})

def _finish(plan: dict, reason: str = "") -> dict:
    plan["available"] = bool(plan["candidates"]) and not reason
    plan["reason"] = reason or ("" if plan["candidates"] else "没有可自动修复的格式问题")
    plan["plan_id"] = _plan_digest(plan)
    return plan

def _resolve(document: Element, locator: object, input_digest: str) -> Element:
    if (not isinstance(locator, dict) or type(locator.get("version")) is not int or locator.get("version") != 1 or locator.get("part") != "word/document.xml"
            or locator.get("input_sha256") != input_digest):
        raise ValueError("缺少与当前文件匹配的精确定位，请重新检测")
    path = locator.get("path")
    if not isinstance(path, list) or len(path) > 100 or any(type(index) is not int or index < 0 for index in path):
        raise ValueError("格式问题的定位无效，请重新检测")
    node = document
    for index in path:
        if index >= len(node):
            raise ValueError("文档结构已变化，请重新检测")
        node = node[index]
    digest = hashlib.sha256(tostring(node, encoding="utf-8")).hexdigest()
    if node.tag != locator.get("tag") or digest != locator.get("node_sha256"):
        raise ValueError("定位处的原格式已变化，请重新检测")
    return node

def _numeric(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

def _action(candidate: dict) -> tuple[list[str], dict[str, str]]:
    target, expected, locator = candidate.get("target"), candidate.get("expected"), candidate.get("locator", {})
    if target in ACADEMIC_TARGETS:
        return academic_action(candidate)
    owner_tag = locator.get("tag")
    if target in {"page.width_mm", "page.height_mm"}:
        if owner_tag != W + "sectPr" or not _numeric(expected) or not 0 < expected <= 2000 or round(expected * 1440 / 25.4) < 1:
            raise ValueError("纸张要求无效或无法定位到文档分节")
        return ["pgSz"], {"w" if target == "page.width_mm" else "h": str(round(expected * 1440 / 25.4))}
    if isinstance(target, str) and target.startswith("page.margins_mm."):
        edge = target.rsplit(".", 1)[-1]
        if owner_tag != W + "sectPr" or edge not in {"top", "bottom", "left", "right"} or not _numeric(expected) or not 0 <= expected <= 200:
            raise ValueError("页边距要求无效或无法定位到文档分节")
        return ["pgMar"], {edge: str(round(expected * 1440 / 25.4))}
    if target == "body.size_pt":
        if owner_tag != W + "r" or not _numeric(expected) or not 0 < expected <= 200 or expected * 2 != round(expected * 2):
            raise ValueError("字号须能以 DOCX 的半磅单位准确表示")
        return ["rPr", "sz"], {"val": str(round(expected * 2))}
    if target == "body.line_spacing":
        if owner_tag != W + "p" or not _numeric(expected) or not 0 < expected <= 200 or abs(expected - round(expected * 240) / 240) > .01:
            raise ValueError("行距要求无法以 DOCX 单位准确表示")
        return ["pPr", "spacing"], {"line": str(round(expected * 240)), "lineRule": "auto"}
    if target == "references.heading_after_lines":
        if owner_tag != W + "p" or not _numeric(expected) or not 0 <= expected <= 200:
            raise ValueError("参考文献标题段后距要求无效或无法定位到段落")
        if abs(expected * 100 - round(expected * 100)) > 1e-8:
            raise ValueError("参考文献标题段后距须能以 DOCX 的百分之一行准确表示")
        return ["pPr", "spacing"], {"afterLines": str(round(expected * 100)), "afterAutospacing": "0"}
    if target == "references.entry_hanging_chars":
        actual = candidate.get("actual")
        size_pt = actual.get("size_pt") if isinstance(actual, dict) else None
        if (owner_tag != W + "p" or not _numeric(expected) or not 0 <= expected <= 200
                or not _numeric(size_pt) or not 0 < size_pt <= 200):
            raise ValueError("参考文献悬挂缩进要求缺少可确定字号或无法定位到段落")
        twips = round(expected * size_pt * 20)
        chars = round(expected * 100)
        if twips < 0 or twips > 28800 or abs(expected * 100 - chars) > 1e-8:
            raise ValueError("参考文献悬挂缩进超出 DOCX 表示范围")
        # Explicit character values override both local and inherited values;
        # keep twip fallbacks consistent for consumers using those attributes.
        return ["pPr", "ind"], {"left": str(twips), "hanging": str(twips),
                                "leftChars": str(chars), "hangingChars": str(chars),
                                "firstLine": "0", "firstLineChars": "0"}
    if target == "body.font" or target in {"body.fonts." + slot for slot in _FONT_SLOTS}:
        slot = locator.get("font_slot")
        if (owner_tag != W + "r" or slot not in _FONT_SLOTS or not isinstance(expected, str)
                or not expected.strip() or len(expected) > 256
                or any(ord(character) < 32 or 0xd800 <= ord(character) <= 0xdfff or ord(character) & 0xffff in {0xfffe, 0xffff} for character in expected)):
            raise ValueError("字体要求无效或缺少明确的文字类型")
        if target != "body.font" and target != "body.fonts." + slot:
            raise ValueError("字体要求与定位的文字类型不一致")
        return ["rPr", "rFonts"], {slot: expected}
    raise ValueError("此问题需人工修改，暂不支持自动修复")

def _expected(profile: dict, candidate: dict) -> object:
    identities = candidate.get("requirement_ids") or ([candidate["requirement_id"]] if candidate.get("requirement_id") else [])
    if identities:
        matched = [item for item in profile.get("scoped_rules", []) if item["id"] in identities
                   and item["target"] == candidate["target"] and not scope_unresolved(item)]
        if not matched or any(expected_key(candidate["target"], item.get("expected")) != expected_key(candidate["target"], matched[0].get("expected")) for item in matched):
            raise ValueError("范围要求与修复项目不一致")
        return matched[0].get("expected")
    settings, target = profile.get("settings", {}), candidate["target"]
    if target in ACADEMIC_TARGETS:
        academic_value = settings
        for key in target.split("."):
            academic_value = academic_value.get(key) if isinstance(academic_value, dict) else None
        return academic_value
    if target.startswith("page."):
        value = settings.get("page", {})
        for key in target.split(".")[1:]:
            value = value.get(key) if isinstance(value, dict) else None
        return value
    body = settings.get("body", {})
    if target == "body.font" or target.startswith("body.fonts."):
        return body.get("fonts", {}).get(candidate["locator"].get("font_slot"), body.get("font"))
    references = settings.get("references", {})
    if target.startswith("references."):
        return references.get(target.removeprefix("references."))
    return body.get(target.removeprefix("body."))

def _complex_size(owner: Element, properties: dict) -> bool:
    from ...plugins.builtin import font_slots
    text = "".join(node.text or "" for node in owner.findall("w:t", NS))
    if "cs" in font_slots(text) or any(unicodedata.bidirectional(character) in {"R", "AL", "AN"} for character in text):
        return True
    return any(W + key in properties and properties[W + key].get(W + "val", "1").strip().lower() not in {"0", "false", "off"}
               for key in ("cs", "rtl"))

def _observed(package: dict, owner: Element, candidate: dict, parents: dict[Element, Element],
              *, check_size_safety: bool = False) -> object:
    from ...documents.docx_semantics import docx_measure, paragraph_properties
    target = candidate["target"]
    if target.startswith("section."):
        return section_observation(owner, target.removeprefix("section.")).value
    if target.startswith("page."):
        chain, attributes = _action(candidate)
        child = owner.find("w:" + chain[-1], NS)
        value = docx_measure(child.get(W + next(iter(attributes))) if child is not None else None,
                             allow_zero=target.startswith("page.margins_mm."),
                             maximum=31680 if target in {"page.width_mm", "page.height_mm"} else 2_147_483_647)
        return round(value * 25.4 / 1440, 3) if value is not None else None
    paragraph = owner
    while paragraph.tag != W + "p":
        paragraph = parents.get(paragraph)
        if paragraph is None:
            return None
    styles = package["styles"]
    content = package.get("content")
    if content is None:
        content = package["content"] = read_docx_content(package["document"], styles, numbering=package.get("numbering"),
                                                        styles_reason=package.get("styles_reason", ""))
    entry = next((item for item in content.paragraphs if item.element is paragraph), None)
    if entry is None:
        return None
    if target.startswith("paragraph.") or (target.startswith("headings.") and owner.tag == W + "p"):
        property_name = target.rsplit(".", 1)[-1]
        if check_size_safety and property_name == "first_line_indent_chars":
            indent = paragraph_properties(entry, styles).get(W + "ind", {})
            if W + "hanging" in indent or W + "hangingChars" in indent:
                raise ValueError("首行缩进与现有悬挂缩进冲突，须在 Word/WPS 中修改")
        return paragraph_observation(entry, styles, property_name).value
    if target == "references.heading_after_lines":
        return paragraph_after_lines(entry, styles, uncertainty=entry.property_uncertainty)
    if target == "references.entry_hanging_chars":
        return reference_hanging(entry, styles)
    if target == "body.line_spacing":
        properties = paragraph_properties(entry, styles, uncertainty=entry.property_uncertainty)
        spacing = properties.get(W + "spacing", {})
        value = docx_measure(spacing.get(W + "line"))
        return value / 240 if value is not None and spacing.get(W + "lineRule", "auto") == "auto" else None
    observed_run = next((run for run in entry.runs if run.element is owner), None)
    if observed_run is None:
        return None
    properties = observed_run.properties
    text = "".join(node.text or "" for node in owner.findall("w:t", NS))
    if target == "body.size_pt" or target.startswith("headings.") and target.endswith(".size_pt"):
        if check_size_safety and _complex_size(owner, properties):
            raise ValueError("复杂文字或从右到左排版的字号需在 Word/WPS 中人工修改")
        return effective_size_pt(text, properties)
    slot = candidate["locator"].get("font_slot")
    slots = effective_font_slots(text, properties)
    if slots is None or slot not in slots:
        return None
    return effective_font_name(slot, properties)

def _safe_owner(owner: Element, parents: dict[Element, Element]) -> None:
    ancestor = owner
    while ancestor is not None:
        if ancestor.tag in {W + "tc", W + "txbxContent"}:
            raise ValueError("表格或文本框中的格式需在对应范围内人工处理")
        if ancestor.tag in _COMPLEX:
            raise ValueError("含域、链接或嵌入对象的位置需人工修改")
        if ancestor.tag == W + "p":
            if any(node.tag in _COMPLEX for node in ancestor.iter()):
                raise ValueError("含域、链接或嵌入对象的段落需人工修改")
        ancestor = parents.get(ancestor)

def build_repair_plan(input_path: Path, result: dict, profile: dict) -> dict:
    """Build a preview exclusively from completed, precisely located checks."""
    input_path = Path(input_path)
    plan: dict[str, Any] = {"version": 1, "input_sha256": result.get("input_sha256", ""),
                            "profile_sha256": _digest(profile), "candidates": [], "skipped": []}
    if input_path.suffix.lower() != ".docx" or result.get("input_format", "docx") != "docx":
        return _finish(plan, "自动修复目前仅支持 DOCX")
    if (result.get("status") not in {"passed", "needs_changes", "review_required"} or result.get("input_unchanged") is not True
            or result.get("execution_errors", 0) or result.get("rules_unchanged") is False):
        return _finish(plan, "本次检测未完整完成，不能据此自动修复")
    if result.get("profile_sha256") != plan["profile_sha256"] or result.get("profile_snapshot") != profile:
        return _finish(plan, "检测方案快照不一致，请重新检测")
    if sha256(input_path) != plan["input_sha256"]:
        raise ValueError("检测文件快照已变化，请重新检测")
    enabled = [identity for identity in ("generic-format", "academic-format") if identity in profile.get("plugins", [])]
    if not enabled:
        return _finish(plan, "此方案未启用可修复的内置格式检查")
    package = read_docx(input_path)
    _, reason = _part_safety(input_path, package)
    if reason:
        return _finish(plan, reason)
    engines = result.get("engines", [])
    if not isinstance(engines, list):
        return _finish(plan, "历史报告缺少精确定位，请重新检测")
    repair_engines = [item for identity in enabled for item in engines
                      if item.get("id") == identity and item.get("status") == "completed"]
    if len(repair_engines) != len(enabled):
        return _finish(plan, "可修复的内置格式检查未完整完成")
    document = package["document"]
    parents = {child: parent for parent in document.iter() for child in parent}
    # Match recorded findings to the same built-in rule on the unchanged source.
    # A report's display text or a forged locator cannot widen the style scope.
    from ...domain import AuditContext
    from ...plugins.academic import AcademicFormatPlugin
    from ...plugins.builtin import GenericPlugin
    keys = ("rule_id", "target", "location", "expected", "actual", "locator", "requirement_id", "requirement_ids",
            "scope_style_ids", "scope_section_indices")
    context = AuditContext(input_path, result.get("kind", "thesis"), input_path.parent, profile.get("settings", {}), cache={"docx": package})
    runners = {"generic-format": GenericPlugin(), "academic-format": AcademicFormatPlugin()}
    live_failures = {identity: {_digest({key: check.get(key) for key in keys})
                                for check in run_scoped_plugin(runners[identity], context, profile).checks if check.get("status") == "failed"}
                     for identity in enabled}
    seen = set()
    missing_locator = False
    for plugin_id, check in ((engine["id"], item) for engine in repair_engines for item in engine.get("checks", [])):
        if check.get("status") in {"passed", "not_applicable"} or check.get("kind", "format") != "format":
            continue
        candidate = {key: check.get(key) for key in keys}
        skip = {key: candidate[key] for key in ("rule_id", "target", "location")}
        try:
            if check.get("status") != "failed" or check.get("plugin") != plugin_id or check.get("actual") is None or check.get("expected") is None:
                raise ValueError(check.get("reason") or "需人工复核，暂不支持自动修复")
            if not isinstance(candidate["locator"], dict):
                missing_locator = True
                raise ValueError("历史报告缺少精确定位，请重新检测")
            if _digest(candidate) not in live_failures[plugin_id]:
                raise ValueError("报告中的问题与当前检测规则不一致，请重新检测")
            candidate["plugin"] = plugin_id
            owner = _resolve(document, candidate["locator"], plan["input_sha256"])
            _safe_owner(owner, parents)
            chain, attributes = _action(candidate)
            if expected_key(candidate["target"], _expected(profile, candidate)) != expected_key(candidate["target"], candidate["expected"]):
                raise ValueError("检测要求与方案快照不一致")
            matching_requirements = [
                requirement for requirement in profile.get("requirements", [])
                if requirement.get("kind") == result.get("kind")
                and requirement.get("target") == candidate["target"]
                and expected_key(candidate["target"], requirement.get("expected")) == expected_key(candidate["target"], candidate["expected"])
                and (not candidate.get("requirement_ids") or requirement["id"] in candidate["requirement_ids"])
            ]
            if (profile.get("school") is not None or matching_requirements) and not any(
                requirement.get("confirmed") and requirement.get("mode") == "automatic"
                and not requirement.get("excluded") for requirement in matching_requirements
            ):
                raise ValueError("对应学校要求尚未确认、已排除或需要人工处理，不能自动修复")
            if candidate.get("requirement_ids"):
                valid_scope = False
                for requirement in matching_requirements:
                    if scope_unresolved(requirement):
                        continue
                    scope_type, scope = requirement_scope(requirement)
                    if scope_type == "sections" and scope:
                        from ...documents.docx_semantics import active_sections
                        sections = active_sections(document)
                        valid_scope = owner in sections and sections.index(owner) + 1 in scope
                    elif scope_type == "styles":
                        paragraph = owner
                        while paragraph is not None and paragraph.tag != W + "p":
                            paragraph = parents.get(paragraph)
                        valid_scope = paragraph is not None and paragraph_style(paragraph, package["styles"]) in scope
                    else:
                        valid_scope = True
                    if valid_scope:
                        break
                if not valid_scope:
                    raise ValueError("修复节点不属于已确认的实际原稿范围")
            if profile.get("school") is not None and candidate["target"].startswith(("body.", "paragraph.")):
                paragraph = owner
                while paragraph is not None and paragraph.tag != W + "p":
                    paragraph = parents.get(paragraph)
                style_id = paragraph_style(paragraph, package["styles"]) if paragraph is not None else None
                scoped_matches = []
                for requirement in matching_requirements:
                    if not requirement.get("confirmed") or requirement.get("mode") != "automatic" or requirement.get("excluded"):
                        continue
                    group_name, property_name = candidate["target"].split(".", 1)
                    group_settings = profile.get("settings", {}).get(group_name, {})
                    scope = requirement.get("scope_style_ids") or group_settings.get("property_style_ids", {}).get(
                        property_name, group_settings.get("style_ids", []))
                    if scope and style_id in scope:
                        scoped_matches.append(requirement)
                if not scoped_matches:
                    raise ValueError("学校要求的正文适用样式尚未确认或与问题不符，不能自动修复")
            if _observed(package, owner, candidate, parents, check_size_safety=True) != candidate["actual"]:
                raise ValueError("原格式与检测结果不一致，请重新检测")
            if candidate["target"].startswith("page."):
                written = round(int(next(iter(attributes.values()))) * 25.4 / 1440, 3)
                if abs(written - candidate["expected"]) > profile.get("settings", {}).get("page", {}).get("tolerance_mm", 1):
                    raise ValueError("要求精度无法以 DOCX 的页面单位准确表示")
            node = owner
            for name in chain:
                children = node.findall("w:" + name, NS)
                if len(children) > 1:
                    raise ValueError("格式属性重复，需人工修改")
                if not children:
                    break
                node = children[0]
            candidate["label"] = TARGET_LABELS.get(candidate["target"], _LABELS.get(candidate["target"], "正文字体"))
            if candidate["target"].startswith("body.font"):
                candidate["label"] += "（" + {"eastAsia": "中文", "ascii": "英文", "hAnsi": "扩展西文", "cs": "复杂文字"}[candidate["locator"]["font_slot"]] + "）"
            identity = _digest(candidate)
            if identity not in seen:
                candidate["id"] = identity
                plan["candidates"].append(candidate)
                seen.add(identity)
                if len(plan["candidates"]) > MAX_REPAIR_CANDIDATES:
                    plan["candidates"] = []
                    return _finish(plan, f"可修复问题超过 {MAX_REPAIR_CANDIDATES} 项，请先分批在 Word/WPS 中调整后重新检测")
        except (ValueError, TypeError, KeyError) as exc:
            plan["skipped"].append({**skip, "reason": str(exc)})
    if sha256(input_path) != plan["input_sha256"]:
        raise ValueError("生成修复预览期间文件发生变化，请重新检测")
    if not plan["candidates"] and missing_locator:
        return _finish(plan, "历史报告缺少精确定位，请重新检测")
    return _finish(plan)
