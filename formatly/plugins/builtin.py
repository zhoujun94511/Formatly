from __future__ import annotations

from dataclasses import fields
import math
import re
from typing import Any
from xml.etree.ElementTree import ParseError, fromstring
from zipfile import BadZipFile, ZipFile

from ..domain import AuditContext, Issue, PluginResult
from ..files import NS, W, read_docx, sha256
from ..documents.docx_locations import DocxLocations
from ..documents.docx_scope import body_scope_roles
from ..documents.docx_semantics import (active_sections, default_paragraph_style, effective_font_name, effective_font_slots,
                              effective_size_pt, font_slots,
                              paragraph_after_lines, paragraph_style, read_docx_content, reference_hanging,
                              docx_measure, paragraph_properties)
from ..documents.fonts import normalize_font_name
from ..documents.ooxml import parse_on_off, read_related_xml
from .citations import body_citation_texts, citation_review_reason, parse_citations


class PackagePlugin:
    id = "docx-package"
    name = "文档读取与完整性"
    description = "按原始格式读取 DOCX、PDF、TXT、MD、JSON，保留解析范围及 OCR 来源，供后续引擎复用。"
    settings_keys = ()
    formats = ("docx", "pdf", "txt", "md", "json")

    @staticmethod
    def probe():
        return True, "基础文档读取可用；PDF 解析依赖及本地 OCR 状态见环境诊断与上传预检"

    def probe_format(self, input_format):
        if input_format == "pdf":
            from ..documents import probe_pdf
            return probe_pdf()
        return self.probe()

    @staticmethod
    def run(context: AuditContext):
        from ..documents import read_document
        from .portable import extraction_summary
        from ..files import write_json
        parsed = read_document(context.input_path, output_dir=context.output_dir / "extraction")
        context.cache["document"] = parsed
        if "docx" in parsed:
            context.cache["docx"] = parsed["docx"]
        evidence = extraction_summary(parsed)
        if evidence is None:
            raise ValueError("文档读取未提供有效提取摘要")
        if "docx" in parsed:
            evidence.update(parts=len(parsed["docx"]["parts"]), uncompressed_bytes=parsed["docx"]["uncompressed_bytes"])
        extraction_path = context.output_dir / "document-extraction.json"
        write_json(extraction_path, {key: value for key, value in parsed.items() if key != "docx"})
        evidence["extraction_sha256"] = sha256(extraction_path)
        checks = [{"rule_id": "package.valid" if parsed["format"] == "docx" else "document.valid", "target": "package",
                   "status": "passed" if parsed["complete"] else "error", "kind": "integrity", "location": "输入原稿",
                   "actual": "原始格式读取完成" if parsed["complete"] else "未完整读取全部页面/内容"}]
        if parsed["requires_review"]:
            checks.append({"rule_id": "extraction.review", "target": "input.text", "kind": "content", "status": "manual",
                           "reason": "识别文本含 OCR、编码不确定或未完整解析内容，须与原件核对", "actual": parsed["warnings"]})
        return PluginResult(evidence=evidence, checks=checks, status="completed" if parsed["complete"] else "incomplete")


def mirrored_page_margins(path) -> bool | None:
    """Return whether left/right margins are inside/outside. None means unknown."""
    try:
        with ZipFile(path) as package:
            types = fromstring(package.read("[Content_Types].xml"))
            related = read_related_xml(
                package, types,
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
                W + "settings",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
                "文档设置", allow_absent=True, conventional_part="word/settings.xml")
    except (OSError, BadZipFile, ParseError, ValueError, KeyError):
        return None
    if related.reason:
        return None
    if related.root is None:
        return False
    flag = related.root.find("w:mirrorMargins", NS)
    if flag is None:
        return False
    return parse_on_off(flag.get(W + "val"), default=True)


class GenericPlugin:
    id = "generic-format"
    name = "可配置格式规则"
    description = "按输入格式核验纸型、内容标题及可证明的排版属性；PDF 正文字体需明确正文区域，无法还原的属性保留复核。"
    settings_keys = ("page", "body", "required_headings", "references")
    formats = ("docx", "pdf", "txt", "md", "json")

    @staticmethod
    def probe():
        return True, "规则引擎可用；文档解析复用共享读取器，按输入格式执行能力预检"

    @staticmethod
    def run(context: AuditContext):
        if context.input_path.suffix.lower() != ".docx":
            from .portable import check_portable
            return check_portable(context)
        package = context.cache.get("docx") or read_docx(context.input_path)
        document, styles = package["document"], package["styles"]
        content = package.get("content") or read_docx_content(document, styles, numbering=package.get("numbering"),
                                                              styles_reason=package.get("styles_reason", ""))
        locations = DocxLocations(document, sha256(context.input_path))
        settings = context.settings
        issues, checks = [], []
        def compare(rule: str, location: str, expected_value: Any, actual_value: Any,
                    allowed_difference: float = 0.0, check_target: str | None = None,
                    locator: dict | None = None, check_style_id: str | None = None,
                    manual_reason: str | None = None) -> None:
            observed, wanted = actual_value, expected_value
            if isinstance(observed, (int, float)) and not math.isfinite(observed):
                observed = actual_value = None
            if rule == "body.font":
                observed, wanted = normalize_font_name(actual_value), normalize_font_name(expected_value)
            differs = actual_value is not None and (
                abs(expected_value - actual_value) > allowed_difference
                if isinstance(expected_value, (int, float)) else wanted != observed
            )
            check_status = "manual" if manual_reason or observed is None or wanted is None else "failed" if differs else "passed"
            checks.append({"rule_id": rule, "target": check_target or rule, "status": check_status, "kind": "format",
                           "location": location, "expected": expected_value, "actual": actual_value, "source": "规则方案"})
            if locator is not None:
                checks[-1]["locator"] = locator
            if check_style_id is not None:
                checks[-1]["style_id"] = check_style_id
            if manual_reason:
                checks[-1]["reason"] = manual_reason
            if check_status == "manual":
                issues.append(Issue(rule, "manual", manual_reason or "未解析到明确属性，须在排版应用中核对", location, expected_value, actual_value))
            elif differs:
                issues.append(Issue(rule, "error", "格式属性与所选方案不符", location, expected_value, actual_value))
        page = settings.get("page", {})
        tolerance = page.get("tolerance_mm", 1)
        sections = active_sections(document)
        mirrored = mirrored_page_margins(context.input_path) if any(
            key in {"left", "right"} for key in page.get("margins_mm", {})) else False
        if page and not sections:
            issues.append(Issue("page.unresolved", "manual", "没有显式分节页面设置，纸型/边距须人工核对"))
            for key in ("width_mm", "height_mm"):
                if key in page:
                    compare("page." + key, "文档页面", page[key], None)
            for key, expected in page.get("margins_mm", {}).items():
                compare("page.margin." + key, "文档页面", expected, None, check_target="page.margins_mm." + key)
        for index, section in enumerate(sections, 1):
            scope = context.cache.get("_active_requirement_scope", {})
            if scope.get("kind") == "sections" and scope.get("values") and index not in scope["values"]:
                continue
            size = section.find("w:pgSz", NS)
            for key, attr in (("width_mm", "w"), ("height_mm", "h")):
                if key in page:
                    value = docx_measure(size.get(W + attr) if size is not None else None, maximum=31680)
                    compare("page." + key, f"第{index}节", page[key], round(value * 25.4 / 1440, 3) if value is not None else None, tolerance,
                            locator=locations.locate(section))
                    checks[-1]["section_index"] = index
            margins = section.find("w:pgMar", NS)
            for key, expected in page.get("margins_mm", {}).items():
                if key in {"left", "right"} and mirrored is not False:
                    compare("page.margin." + key, f"第{index}节", expected, None, check_target="page.margins_mm." + key,
                            locator=locations.locate(section),
                            manual_reason="对称页边距下左右表示内外侧，不能按物理左右边通过" if mirrored
                            else "文档设置无法确认是否为对称页边距")
                    checks[-1]["section_index"] = index
                    continue
                value = docx_measure(margins.get(W + key) if margins is not None else None, allow_zero=True)
                compare("page.margin." + key, f"第{index}节", expected, round(value * 25.4 / 1440, 3) if value is not None else None, tolerance,
                        check_target="page.margins_mm." + key, locator=locations.locate(section))
                checks[-1]["section_index"] = index
        paragraphs = content.paragraphs
        texts = [paragraph.text for paragraph in paragraphs]
        normalize = lambda text_value: "".join(text_value.split()).casefold()
        for heading in settings.get("required_headings", []):
            found = any(normalize(heading) == normalize(text) for text in texts)
            heading_status = "passed" if found else "manual" if content.requires_review else "failed"
            checks.append({"rule_id": "structure.heading", "target": "required_heading", "status": heading_status,
                           "kind": "format", "location": "文档结构", "expected": heading, "actual": heading if found else "未找到"})
            if not found:
                issues.append(Issue("structure.heading", "manual" if heading_status == "manual" else "error",
                                    "文档含未确认显示内容，标题须核对" if heading_status == "manual" else "未找到方案要求的独立标题段",
                                    "文档结构", heading, "未找到"))
        if content.requires_review:
            checks.append({"rule_id": "docx.content_review", "target": "input.text", "status": "manual", "kind": "content",
                           "reason": "；".join(content.warnings), "location": "DOCX 显示内容"})
        body = settings.get("body", {})
        matched = 0
        default_style = default_paragraph_style(styles)
        selected_styles = body.get("style_ids", [default_style])
        property_styles = body.get("property_style_ids", {})
        inspected = set()
        scope_roles = body_scope_roles(document, styles, paragraphs,
                                       exclude_containers=bool(context.cache.get("_active_requirement_scope")))
        excluded_paragraphs, uncertain_paragraphs = [], []

        def applies(property_name, style):
            return style in property_styles.get(property_name, selected_styles)

        matched_styles = set()
        if any(k in body for k in ("font", "fonts", "size_pt", "line_spacing")):
            for paragraph in paragraphs:
                p, text, index = paragraph.element, paragraph.text, paragraph.index
                style_id = paragraph_style(p, styles)
                if not text or style_id not in selected_styles:
                    continue
                role, scope_reason = scope_roles.get(index, (None, ""))
                if role is not None and role != "uncertain":
                    excluded_paragraphs.append({"location": f"XML段{index}", "style_id": style_id, "role": role, "reason": scope_reason})
                    checks.append({"rule_id": "body.scope", "target": "body.scope", "kind": "content", "status": "not_applicable",
                                   "location": f"XML段{index}：{text[:60]}", "style_id": style_id, "actual": role,
                                   "reason": scope_reason + "；不套用正文格式要求", "locator": locations.locate(p)})
                    continue
                uncertain_reason = scope_reason if role == "uncertain" else None
                if uncertain_reason:
                    uncertain_paragraphs.append({"location": f"XML段{index}", "style_id": style_id, "reason": uncertain_reason})
                matched += 1
                matched_styles.add(style_id)
                loc = f"XML段{index}：{text[:60]}"
                pprops = paragraph_properties(paragraph, styles, uncertainty=paragraph.property_uncertainty)
                if "line_spacing" in body and applies("line_spacing", style_id):
                    inspected.add("line_spacing")
                    spacing = pprops.get(W + "spacing", {})
                    line = docx_measure(spacing.get(W + "line"))
                    rule_name = spacing.get(W + "lineRule", "auto")
                    if line is not None and rule_name == "auto":
                        actual, spacing_reason = line / 240, uncertain_reason
                    else:
                        actual = None
                        spacing_reason = uncertain_reason or (
                            f"行距模式为{rule_name}，不能按倍数行距比较" if line is not None else None)
                    compare("body.line_spacing", loc, body["line_spacing"], actual, .01, locator=locations.locate(p), check_style_id=style_id,
                            manual_reason=spacing_reason)
                for observed_run in paragraph.runs:
                    run_index, run, run_text = observed_run.index, observed_run.element, observed_run.text
                    if not run_text.strip():
                        continue
                    rprops = observed_run.properties
                    run_loc = loc + f" / run{run_index}"
                    if "size_pt" in body and applies("size_pt", style_id):
                        inspected.add("size_pt")
                        compare("body.size_pt", run_loc, body["size_pt"], effective_size_pt(run_text, rprops), .01,
                                locator=locations.locate(run), check_style_id=style_id, manual_reason=uncertain_reason)
                    if "font" in body or "fonts" in body:
                        fonts = rprops.get(W + "rFonts", {})
                        slots = effective_font_slots(run_text, rprops)
                        for key in sorted(slots if slots is not None else font_slots(run_text)):
                            expected = body.get("fonts", {}).get(key, body.get("font"))
                            property_key = "fonts." + key if key in body.get("fonts", {}) else "font"
                            if expected is not None and not applies(property_key, style_id):
                                continue
                            if expected is None:
                                checks.append({"rule_id": "body.font", "target": "body.fonts." + key,
                                               "status": "not_checked", "kind": "format", "location": run_loc + " / " + key,
                                               "actual": fonts.get(W + key), "style_id": style_id, "reason": "该文字脚本未配置字体要求"})
                                continue
                            inspected.add(property_key)
                            value = effective_font_name(key, rprops) if slots is not None else None
                            target = "body.fonts." + key if key in body.get("fonts", {}) else "body.font"
                            compare("body.font", run_loc + " / " + key, expected, value, check_target=target,
                                    locator=locations.locate(run, font_slot=key), check_style_id=style_id, manual_reason=uncertain_reason)
            if not matched:
                issues.append(Issue("body.no_matching_style", "manual", "没有匹配正文样式的非空段落，正文格式未检测", expected=body.get("style_ids", [default_style])))
                for key in ("font", "size_pt", "line_spacing"):
                    if key in body:
                        compare("body." + key, "正文样式范围", body[key], None)
                for key, expected in body.get("fonts", {}).items():
                    compare("body.font", "正文样式范围", expected, None, check_target="body.fonts." + key)
            if matched:
                required = {key: body[key] for key in ("font", "size_pt", "line_spacing") if key in body}
                required.update({"fonts." + key: value for key, value in body.get("fonts", {}).items()})
                for key, expected in required.items():
                    if key in inspected:
                        continue
                    target = "body." + key
                    compare("body.font" if key.startswith("fonts.") or key == "font" else target,
                            "正文样式范围", expected, None, check_target=target)
            if "style_ids" in body:
                checks.append({"rule_id": "body.style_selection", "target": "body.style_ids", "status": "passed" if matched else "manual",
                               "kind": "content", "location": "正文样式范围", "expected": body["style_ids"], "actual": sorted(matched_styles)})

        references = settings.get("references", {})
        if references:
            # Reference rules are deliberately explicit.  A profile can opt in
            # to each rule independently; leaving a key out keeps that aspect
            # outside the automatic coverage claim.
            reference_heading = references.get("heading", "参考文献")
            normalize_reference = lambda reference_text: "".join(reference_text.split()).casefold()
            heading = next((paragraph for paragraph in paragraphs
                            if normalize_reference(paragraph.text) == normalize_reference(reference_heading)), None)
            heading_required = any(key in references for key in ("heading", "heading_after_lines", "entry_hanging_chars"))

            def reference_check(check_rule_id, check_target, expected_value, actual_value, check_status, location,
                                *, check_reason=None, check_locator=None, check_kind="format", check_style_id=None):
                check = {"rule_id": check_rule_id, "target": check_target, "status": check_status, "kind": check_kind,
                         "location": location, "expected": expected_value, "actual": actual_value, "source": "规则方案"}
                if check_reason:
                    check["reason"] = check_reason
                if check_locator is not None:
                    check["locator"] = check_locator
                if check_style_id is not None:
                    check["style_id"] = check_style_id
                checks.append(check)
                if check_status == "failed":
                    issues.append(Issue(check_rule_id, "error", check_reason or "参考文献格式与所选方案不符", location,
                                        expected_value, actual_value))
                elif check_status == "manual":
                    issues.append(Issue(check_rule_id, "manual", check_reason or "参考文献属性无法自动确认，请人工核对", location,
                                        expected_value, actual_value))

            if heading is None and heading_required:
                reference_check("references.heading", "references.heading", reference_heading, None,
                                "manual" if content.requires_review else "failed", "参考文献结构",
                                check_reason="未找到参考文献章节标题", check_kind="content")
            else:
                if "heading_after_lines" in references and heading is not None:
                    actual_after = paragraph_after_lines(heading, styles, uncertainty=heading.property_uncertainty)
                    valid = actual_after is not None and abs(actual_after - references["heading_after_lines"]) <= .01
                    reference_check("references.heading_after_lines", "references.heading_after_lines",
                                    references["heading_after_lines"], actual_after,
                                    "manual" if actual_after is None else "passed" if valid else "failed",
                                    f"XML段{heading.index}：{heading.text[:60]}",
                                    check_reason="参考文献章节标题段后距无法从 DOCX 段落属性确定" if actual_after is None else
                                    "参考文献章节标题段后距与所选方案不符" if not valid else None,
                                    check_locator=locations.locate(heading.element), check_style_id=paragraph_style(heading.element, styles))

                entry_style_ids = set(references.get("entry_style_ids", []))
                entry_pattern = re.compile(r"^\s*\[\d+]")
                entries = []
                for paragraph in paragraphs:
                    if heading is not None and paragraph.index <= heading.index:
                        continue
                    match = entry_pattern.match(paragraph.text)
                    if match is None:
                        continue
                    style_id = paragraph_style(paragraph.element, styles)
                    if entry_style_ids and style_id not in entry_style_ids:
                        continue
                    entries.append((paragraph, style_id))

                if "entry_hanging_chars" in references:
                    tolerance_chars = references.get("entry_hanging_tolerance_chars", .01)
                    if not entries:
                        reference_check("references.entry_hanging_chars", "references.entry_hanging_chars",
                                        references["entry_hanging_chars"], None,
                                        "manual" if content.requires_review else "failed", "参考文献条目",
                                        check_reason="未找到可核验的参考文献条目")
                    for paragraph, style_id in entries:
                        observed_hanging = reference_hanging(paragraph, styles)
                        actual_chars = observed_hanging["chars"]
                        if actual_chars is None:
                            status = "manual"
                            reason = "参考文献条目缺少可确定的字号或悬挂缩进属性"
                        else:
                            status = "passed" if abs(actual_chars - references["entry_hanging_chars"]) <= tolerance_chars else "failed"
                            reason = None if status == "passed" else "参考文献条目悬挂缩进与所选方案不符"
                        reference_check("references.entry_hanging_chars", "references.entry_hanging_chars",
                                        references["entry_hanging_chars"],
                                        observed_hanging, status,
                                        f"XML段{paragraph.index}：{paragraph.text[:60]}", check_reason=reason,
                                        check_locator=locations.locate(paragraph.element), check_style_id=style_id)

                citation_order = references.get("citation_order")
                unique_configured = "citation_unique" in references
                if (citation_order and citation_order != "none") or unique_configured:
                    citations = parse_citations(body_citation_texts(
                        [paragraph.text for paragraph in paragraphs if heading is None or paragraph.index < heading.index],
                        heading_found=heading is not None))
                    citation_numbers = citations.numbers
                    document_evidence = context.cache.get("document") or {
                        "format": "docx", "complete": True, "requires_review": content.requires_review,
                        "text": "\n".join(texts), "entries": [{"method": "text"}], "docx": package}
                    uncertainty = citation_review_reason(document_evidence, citations)
                    citation_start = references.get("citation_start", 1)
                    first_occurrences = []
                    seen = set()
                    for number in citation_numbers:
                        if number not in seen:
                            seen.add(number)
                            first_occurrences.append(number)
                    if citation_order and citation_order != "none":
                        expected_first = list(range(citation_start, citation_start + len(first_occurrences)))
                        actual_order = {"sequence": citation_numbers, "first_occurrences": first_occurrences,
                                        "parse_warnings": citations.warnings}
                        status = "manual" if uncertainty else "passed" if first_occurrences == expected_first else "failed"
                        reference_check("references.citation_order", "references.citation_order",
                                        citation_order, actual_order, status,
                                        "正文参考文献引用", check_reason=uncertainty or (
                                        "正文参考文献首次引用顺序未按要求递增" if status == "failed" else None),
                                        check_kind="content")
                    unique_required = references.get("citation_unique", False)
                    if unique_configured and unique_required:
                        counts = {}
                        for number in citation_numbers:
                            counts[number] = counts.get(number, 0) + 1
                        duplicates = sorted(number for number, count in counts.items() if count > 1)
                        reference_check("references.citation_unique", "references.citation_unique", True,
                                        {"unique": not duplicates, "duplicates": duplicates, "parse_warnings": citations.warnings},
                                        "manual" if uncertainty else "passed" if not duplicates else "failed", "正文参考文献引用",
                                        check_reason=uncertainty or ("正文重复引用同一条参考文献" if duplicates else None), check_kind="content")
        issues.append(Issue("layout.visual_review", "manual", "属性检测已完成；分页、遮挡、目录页码与打印效果仍需结合实际页面复核", "实际页面"))
        checks.append({"rule_id": "layout.visual_review", "target": "layout.visual", "status": "manual", "kind": "format",
                       "location": "实际页面", "reason": "属性检查不能证明分页、遮挡、目录页码与打印效果"})
        paired = None
        status = "completed"
        if context.pdf_path:
            from .portable import inspect_paired_pdf
            paired_result = inspect_paired_pdf(context, "\n".join(texts))
            issues.extend(paired_result.issues)
            checks.extend(paired_result.checks)
            paired = paired_result.evidence
            status = paired_result.status
        return PluginResult(issues, {"paired_pdf": paired, "paragraph_count": len(paragraphs), "section_count": len(sections), "body_paragraphs_checked": matched,
                                     "nonempty_paragraphs": sum(bool(text) for text in texts),
                                     "outside_body_style_scope": sum(bool(text) for text in texts) - matched - len(excluded_paragraphs),
                                     "excluded_non_body_paragraphs": excluded_paragraphs,
                                     "uncertain_body_paragraphs": uncertain_paragraphs,
                                     "matched_style_ids": sorted(matched_styles)}, checks=checks, status=status)


class LegacyPlugin:
    id = "legacy-school"
    name = "可选外部专项引擎"
    description = (
        "可选的外部专项引擎。日常请用「学校要求」生成方案或选用预置方案；"
        "仅在已配置外部引擎时增强模板、字体与 PDF 核验。"
    )
    settings_keys = ()
    kinds = ("thesis", "intern")
    formats = ("docx",)

    def __init__(self, data_dir=None):
        from ..adapters.legacy import resolve_engine_settings
        self._configuration = None
        self._last_diagnostics = None
        try:
            self._configuration = resolve_engine_settings(data_dir)
        except (OSError, RuntimeError, ValueError):
            # Invalid optional configuration must not stop the core service.
            pass

    def probe(self):
        from ..adapters.legacy import probe_legacy, public_engine_info
        if self._configuration is None:
            result = {"available": False, "stage": "error", "discovery": "configuration",
                      "checks": [{"id": "configuration", "status": "error"}],
                      "reason": "可选外部专项引擎的本机配置无效；请在运行主机修复配置后重启服务"}
        else:
            root, python, settings = self._configuration
            result = probe_legacy(root=root, python=python)
            result["public"].update(settings)
        self._last_diagnostics = public_engine_info(result)
        return result["available"], result["reason"]

    def diagnostics(self):
        """Use the diagnostic from this registry probe, avoiding a second process."""
        if self._last_diagnostics is None:
            self.probe()
        return self._last_diagnostics

    def run(self, context: AuditContext):
        from ..adapters.legacy import run_legacy
        if self._configuration is None:
            raise RuntimeError("可选外部专项引擎的本机配置无效；请在运行主机修复配置后重启服务")
        root, python, _ = self._configuration
        raw = run_legacy(context.input_path, context.kind, context.output_dir, context.pdf_path,
                         context.render_word, root=root, python=python)
        issue_fields = {item.name for item in fields(Issue)}
        issues = [Issue(**{key: value for key, value in item.items() if key in issue_fields}) for item in raw.get("issues", [])]
        from ..adapters.legacy_worker import engine_failures
        failures = engine_failures(raw)
        checks = [{"rule_id": "legacy.coverage", "target": "legacy.rules", "kind": "format", "status": "manual",
                   "reason": "专项引擎提供问题列表；逐规则通过范围须结合原始证据和已接受例外复核"}]
        return PluginResult(issues, {"report": "legacy/report.json", "raw_engines": raw.get("engines", {}),
                                     "accepted_exceptions": raw.get("accepted_exceptions", []), "incomplete_engines": failures},
                            status="incomplete" if failures else "completed", checks=checks)

