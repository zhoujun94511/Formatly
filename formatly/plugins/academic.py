"""Native checks for configurable academic DOCX typography."""
from __future__ import annotations

import math

from ..domain import AuditContext, Issue, PluginResult
from ..documents.academic_semantics import Observation, heading_level, paragraph_observation, section_observation
from ..documents.docx_locations import DocxLocations
from ..documents.docx_scope import body_scope_roles
from ..documents.docx_semantics import (active_sections, effective_font_name, effective_font_slots,
                                        effective_size_pt, paragraph_style, read_docx_content)
from ..documents.fonts import normalize_font_name
from ..files import NS, read_docx, sha256
from .academic_rules import PARAGRAPH_PROPERTIES, TARGET_LABELS, configured_academic_values

_HEADING_PROPERTIES = ("size_pt", "alignment", "before_lines", "after_lines")
_SECTION_PROPERTIES = ("gutter_mm", "header_distance_mm", "footer_distance_mm", "columns")


class AcademicFormatPlugin:
    id = "academic-format"
    name = "论文与报告排版"
    description = "核验显式正文范围内的缩进与段距、结构标题排版及分节距离和分栏。"
    settings_keys = ("paragraph", "headings", "section")
    formats = ("docx", "pdf", "txt", "md", "json")
    kinds = ("thesis", "intern", "certificate")

    @staticmethod
    def probe() -> tuple[bool, str]:
        return True, "内置排版检测可用；DOCX 按可读取属性核验，其余格式保留逐项能力说明"

    @staticmethod
    def validate_settings(settings: dict) -> None:
        from .academic_rules import validate_academic_settings
        validate_academic_settings(settings)

    @staticmethod
    def run(context: AuditContext) -> PluginResult:
        configured = dict(configured_academic_values(context.settings))
        if not configured:
            return PluginResult(checks=[{"rule_id": "academic.settings", "target": "academic.settings", "kind": "format",
                                         "status": "not_checked", "location": "规则方案", "reason": "尚未配置论文与报告排版要求"}])
        if context.input_path.suffix.lower() != ".docx":
            return PluginResult(checks=[{"rule_id": target, "target": target, "label": TARGET_LABELS[target], "kind": "format", "status": "unsupported",
                                         "location": "输入原稿", "expected": expected, "actual": None,
                                         "reason": "该属性需读取 DOCX 排版设置；当前文件格式无法可靠还原"}
                                        for target, expected in configured.items()])
        package = context.cache.get("docx")
        if package is None:
            package = read_docx(context.input_path)
            context.cache["docx"] = package
        document, styles = package["document"], package["styles"]
        content = package.get("content")
        if content is None:
            content = read_docx_content(document, styles, numbering=package.get("numbering"),
                                        styles_reason=package.get("styles_reason", ""))
            package["content"] = content
        locations = DocxLocations(document, sha256(context.input_path))
        issues: list[Issue] = []
        checks: list[dict] = []
        roles = body_scope_roles(document, styles, content.paragraphs,
                                 exclude_containers=bool(context.cache.get("_active_requirement_scope")))
        examined = set()

        def record(check_target: str, observation: Observation, check_location: str, *, check_locator: dict | None = None,
                   check_style_id: str | None = None, manual_reason: str = "", check_status: str | None = None) -> None:
            expected_value, observed_value = configured[check_target], observation.value
            check_reason = manual_reason or observation.reason
            if isinstance(observed_value, (int, float)) and not math.isfinite(observed_value):
                observed_value = None
            if check_status is None:
                if check_reason or observed_value is None:
                    check_status = "manual"
                else:
                    if ".fonts." in check_target:
                        known, wanted = normalize_font_name(observed_value), normalize_font_name(expected_value)
                        check_status = "manual" if known is None or wanted is None else "passed" if known == wanted else "failed"
                    elif isinstance(expected_value, (int, float)) and isinstance(observed_value, (int, float)):
                        check_status = "passed" if abs(expected_value - observed_value) <= (.05 if check_target.startswith("section.") else .01) else "failed"
                    else:
                        check_status = "passed" if expected_value == observed_value else "failed"
            check = {"rule_id": check_target, "target": check_target, "label": TARGET_LABELS[check_target], "kind": "format", "status": check_status, "location": check_location,
                     "expected": expected_value, "actual": observed_value, "source": "规则方案"}
            if check_locator is not None:
                check["locator"] = check_locator
            if check_style_id is not None:
                check["style_id"] = check_style_id
            if check_reason:
                check["reason"] = check_reason
            checks.append(check)
            if check_status in {"manual", "failed"}:
                issues.append(Issue(check_target, "manual" if check_status == "manual" else "error",
                                    check_reason or ("未解析到明确属性，须在排版应用中核对" if check_status == "manual" else "格式属性与所选方案不符"),
                                    check_location, expected_value, observed_value))

        paragraph_rules = context.settings.get("paragraph", {})
        for key in PARAGRAPH_PROPERTIES:
            target = "paragraph." + key
            if target not in configured:
                continue
            selected = paragraph_rules.get("property_style_ids", {}).get(key, paragraph_rules.get("style_ids", []))
            if not selected:
                record(target, Observation(reason="须为该要求明确指定正文样式范围"), "正文样式范围")
                continue
            matched = 0
            for paragraph in content.paragraphs:
                style_id = paragraph_style(paragraph.element, styles)
                if not paragraph.text.strip() or style_id not in selected:
                    continue
                role, scope_reason = roles.get(paragraph.index, (None, ""))
                location = f"XML段{paragraph.index}：{paragraph.text[:60]}"
                locator = locations.locate(paragraph.element, style_id=style_id)
                if role is not None and role != "uncertain":
                    record(target, Observation(role, scope_reason + "；不套用正文要求"), location,
                           check_locator=locator, check_style_id=style_id, check_status="not_applicable")
                    continue
                matched += 1
                examined.add(paragraph.index)
                record(target, paragraph_observation(paragraph, styles, key), location, check_locator=locator,
                       check_style_id=style_id, manual_reason=scope_reason if role == "uncertain" else "")
            if not matched:
                record(target, Observation(reason="没有匹配正文样式范围的可检测段落"), "正文样式范围")

        for level, heading_rules in context.settings.get("headings", {}).items():
            targets = {key: value for key, value in configured.items() if key.startswith(f"headings.{level}.")}
            if not targets:
                continue
            headings = [paragraph for paragraph in content.paragraphs
                        if paragraph.text.strip() and heading_level(paragraph, styles) == int(level)
                        and (context.cache.get("_active_requirement_scope", {}).get("kind") != "styles"
                             or paragraph_style(paragraph.element, styles) in context.cache["_active_requirement_scope"].get("values", []))]
            if not headings:
                for target in targets:
                    record(target, Observation(reason="没有可由大纲级别或标题样式继承确认的对应标题"), f"{level}级标题范围")
                continue
            for paragraph in headings:
                examined.add(paragraph.index)
                style_id = paragraph_style(paragraph.element, styles)
                location = f"XML段{paragraph.index}：{paragraph.text[:60]}"
                locator = locations.locate(paragraph.element, style_id=style_id)
                for key in _HEADING_PROPERTIES:
                    if key not in heading_rules or key == "size_pt":
                        continue
                    record(f"headings.{level}.{key}", paragraph_observation(paragraph, styles, key), location,
                           check_locator=locator, check_style_id=style_id)
                inspected_fonts: set[str] = set()
                inspected_size = False
                visible_runs = {run.element for run in paragraph.runs}
                nested_runs = {run for nested in paragraph.element.findall(".//w:p", NS)
                               for run in nested.findall(".//w:r", NS)}
                partial_reason = "标题含未用于核验的隐藏、修订或兼容分支文字，须核对完整标题排版" if any(
                    run not in visible_runs and run not in nested_runs and any((node.text or "").strip() for node in run.findall(".//w:t", NS))
                    for run in paragraph.element.findall(".//w:r", NS)) else ""
                for run in paragraph.runs:
                    if not run.text.strip():
                        continue
                    run_location = location + f" / run{run.index}"
                    run_locator = locations.locate(run.element, style_id=style_id)
                    if "size_pt" in heading_rules:
                        inspected_size = True
                        record(f"headings.{level}.size_pt", Observation(effective_size_pt(run.text, run.properties)), run_location,
                               check_locator=run_locator, check_style_id=style_id, manual_reason=partial_reason)
                    slots = effective_font_slots(run.text, run.properties)
                    for slot in heading_rules.get("fonts", {}):
                        if slots is not None and slot not in slots:
                            continue
                        inspected_fonts.add(slot)
                        actual = effective_font_name(slot, run.properties) if slots is not None else None
                        record(f"headings.{level}.fonts.{slot}", Observation(actual), run_location + " / " + slot,
                               check_locator=locations.locate(run.element, style_id=style_id, font_slot=slot), check_style_id=style_id,
                               manual_reason=partial_reason)
                if "size_pt" in heading_rules and not inspected_size:
                    record(f"headings.{level}.size_pt", Observation(reason="标题没有可核验的可见文字片段"), location,
                           check_locator=locator, check_style_id=style_id)
                for slot in heading_rules.get("fonts", {}):
                    if slot not in inspected_fonts:
                        record(f"headings.{level}.fonts.{slot}", Observation(reason="标题没有该字体槽对应的可见文字"), location,
                               check_locator=locator, check_style_id=style_id, check_status="manual" if content.requires_review else "not_applicable")

        sections = active_sections(document)
        for key in _SECTION_PROPERTIES:
            target = "section." + key
            if target not in configured:
                continue
            if not sections:
                record(target, Observation(reason="未找到有效的正文分节设置"), "文档分节")
            for index, section in enumerate(sections, 1):
                scope = context.cache.get("_active_requirement_scope", {})
                if scope.get("kind") == "sections" and scope.get("values") and index not in scope["values"]:
                    continue
                record(target, section_observation(section, key), f"第{index}节", check_locator=locations.locate(section))
                checks[-1]["section_index"] = index
                if key == "gutter_mm" and checks[-1]["status"] != "manual":
                    width = checks[-1]
                    checks.append({**width, "rule_id": "section.gutter_direction", "target": "section.gutter_direction",
                                   "status": "manual", "expected": "装订方向", "actual": None,
                                   "reason": "仅核对装订线宽度，装订方向需单独复核"})
        return PluginResult(issues=issues, checks=checks,
                            evidence={"paragraphs_checked": len(examined), "sections": len(sections),
                                      "configured_targets": sorted(configured), "content_warnings": content.warnings})
