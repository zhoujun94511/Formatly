"""Checks backed by observable PDF/text/JSON evidence, without DOCX conversion."""
from __future__ import annotations

import re
from collections import Counter

from ..documents import read_document
from ..documents.fonts import normalize_font_name
from ..domain import AuditContext, Issue, PluginResult
from ..privacy import public_ocr_information, redact_local_paths
from .citations import body_citation_texts, citation_review_reason, parse_citations


def ocr_review_summary(pages):
    """Expose bounded observations without promoting a second OCR to ground truth."""
    observations = [{**review, "page": page.get("number")}
                    for page in pages for review in page.get("ocr_reviews", [])
                    if isinstance(review, dict)]
    if not observations:
        return None
    priority = {"disagreement": 0, "not_checked": 1, "consistent": 2}

    def observation_priority(observation):
        status = observation.get("status")
        return priority.get(status, 3) if isinstance(status, str) else 3

    selected = sorted(observations, key=observation_priority)[:40]
    keys = ("page", "location", "status", "reason", "canonical_source", "primary_text", "bbox",
            "min_word_confidence", "low_confidence_word_count", "alternative", "differences")
    return {"observation_count": len(observations),
            "disagreement_count": sum(item.get("status") == "disagreement" for item in observations),
            "consistent_count": sum(item.get("status") == "consistent" for item in observations),
            "not_checked_count": sum(item.get("status") == "not_checked" for item in observations),
            "observations": [{key: item[key] for key in keys if key in item} for item in selected],
            "truncated": len(observations) > len(selected)}


def extraction_summary(document):
    """Small report metadata; full text/coordinates remain a separate artifact."""
    if not document:
        return None
    pages = document.get("pages", [])
    summary = {"format": document["format"], "complete": document.get("complete", False),
            "requires_review": document.get("requires_review", False), "warnings": document.get("warnings", []),
            "encoding": document.get("encoding"), "schema": document.get("json_schema"),
            "ocr": public_ocr_information(document["ocr"]) if isinstance(document.get("ocr"), dict) else None,
            "page_count": document.get("page_count", len(pages)), "processed_pages": len(pages),
            "entry_count": len(document.get("entries", [])),
            "pages": [{key: page[key] for key in ("number", "width_mm", "height_mm", "method", "confidence", "hidden_characters", "unverified_characters") if key in page}
                      for page in pages], "methods": sorted({entry.get("method", "text") for entry in document.get("entries", [])})}
    review = ocr_review_summary(pages)
    if review is not None:
        summary["ocr_review"] = review
    return summary


def _heading(text):
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"\s+#+\s*$", "", text)
    return "".join(text.split()).casefold()


def check_portable(context: AuditContext):
    document = context.cache.get("document") or read_document(context.input_path, output_dir=context.output_dir / "extraction")
    context.cache["document"] = document
    settings, checks = context.settings, []
    pages, entries = document.get("pages", []), document.get("entries", [])
    is_pdf = document["format"] == "pdf"
    markdown = None
    if document["format"] == "md":
        from ..documents.markdown import heading_text, visible_text
        markdown = visible_text(document.get("text", ""))
        entries = markdown.entries
        normalize_heading = heading_text
    else:
        normalize_heading = _heading

    def add(check_target, expected_value, actual_value=None, check_status="unsupported", reason="此输入格式不保存该排版属性", location="原始文档", kind="format", rule=None):
        checks.append({"rule_id": rule or check_target, "target": check_target, "kind": kind, "status": check_status,
                       "location": location, "expected": expected_value, "actual": actual_value, "reason": reason,
                       "source": "规则方案与原始 " + document["format"].upper() + " 证据"})

    page_settings = settings.get("page", {})
    for key in ("width_mm", "height_mm"):
        if key not in page_settings:
            continue
        if not is_pdf:
            add("page." + key, page_settings[key])
        elif not pages:
            add("page." + key, page_settings[key], check_status="not_checked", reason="没有取得 PDF 页面尺寸")
        else:
            for page in pages:
                actual = page.get(key)
                valid = actual is not None and abs(actual - page_settings[key]) <= page_settings.get("tolerance_mm", 1)
                add("page." + key, page_settings[key], actual, "manual" if actual is None else "passed" if valid else "failed",
                    "按实际 PDF 页面尺寸核验", f"PDF第{page['number']}页")
    for side, value in page_settings.get("margins_mm", {}).items():
        add("page.margin_" + side, value, reason="PDF 内容边界不能证明 Word 页边距设置" if is_pdf else "文本没有实际纸张页边距",
            rule="page.margin_" + side)
        # School targets use the settings path, not the historical issue ID.
        checks[-1]["target"] = "page.margins_mm." + side

    for heading in settings.get("required_headings", []):
        found = [entry for entry in entries if normalize_heading(entry["text"]) == normalize_heading(heading)]
        certain = [entry for entry in found if entry.get("method", "text") != "ocr"]
        markdown_review = markdown is not None and markdown.requires_review
        if markdown_review:
            certain = []
        uncertain = document.get("requires_review") or not document.get("complete", False) or markdown_review
        status = "passed" if certain else "manual" if found or uncertain else "failed"
        add("required_heading", heading, [{"text": entry["text"], "location": entry["location"], "method": entry.get("method", "text")} for entry in found],
            status, "按可核对的独立文本行核对标题；OCR 命中或未完整提取时的缺失须人工核对", "独立文本行/标题块", "content", "heading.required")

    body = settings.get("body", {})
    for key in ("style_ids", "line_spacing"):
        if key in body:
            add("body." + key, body[key], reason="PDF 不保留 Word 段落样式/行距设置" if is_pdf else "此文本格式不保留实际段落排版",
                kind="content" if key == "style_ids" else "format")
    references = settings.get("references", {})
    if references:
        # Text formats can verify citation order and uniqueness when the text
        # extraction is complete. Word paragraph spacing and indentation are
        # intentionally reported as unsupported because they are not encoded.
        lines = ([text for _, text in markdown.lines] if markdown is not None else
                 [line for line in document.get("text", "").splitlines() if line.strip()])
        heading = references.get("heading", "参考文献")
        normalize_reference = normalize_heading if markdown is not None else lambda reference_text: "".join(reference_text.split()).casefold()
        heading_index = next((index for index, line in enumerate(lines)
                              if normalize_reference(line) == normalize_reference(heading)), None)
        if "heading_after_lines" in references:
            add("references.heading_after_lines", references["heading_after_lines"],
                reason="PDF/文本格式不保留 Word 标题段后距设置")
        if "entry_hanging_chars" in references:
            add("references.entry_hanging_chars", references["entry_hanging_chars"],
                reason="PDF/文本格式不保留 Word 参考文献悬挂缩进设置")
        check_order = bool(references.get("citation_order") and references.get("citation_order") != "none")
        check_unique = references.get("citation_unique", False)
        if check_order or check_unique:
            citation_text = "\n".join(body_citation_texts(
                lines[:heading_index] if heading_index is not None else lines,
                heading_found=heading_index is not None))
            citations = parse_citations([citation_text])
            citation_numbers = citations.numbers
            first_occurrences, seen = [], set()
            for number in citation_numbers:
                if number not in seen:
                    seen.add(number)
                    first_occurrences.append(number)
            start = references.get("citation_start", 1)
            expected_first = list(range(start, start + len(first_occurrences)))
            citation_document = ({**document, "requires_review": True}
                                 if markdown is not None and markdown.requires_review else document)
            uncertainty = citation_review_reason(citation_document, citations)
            if check_order:
                actual_order = {"sequence": citation_numbers, "first_occurrences": first_occurrences,
                                "parse_warnings": citations.warnings}
                status = "manual" if uncertainty else "passed" if first_occurrences == expected_first else "failed"
                add("references.citation_order", references["citation_order"], actual_order, status,
                    uncertainty or ("正文参考文献首次引用顺序未按要求递增" if status == "failed" else "按完整提取文本核对引用首次出现顺序"),
                    "正文参考文献引用", "content", "references.citation_order")
            if check_unique:
                counts = Counter(citation_numbers)
                duplicates = sorted(number for number, count in counts.items() if count > 1)
                add("references.citation_unique", True, {"unique": not duplicates, "duplicates": duplicates,
                                                       "parse_warnings": citations.warnings},
                    "manual" if uncertainty else "failed" if duplicates else "passed",
                    uncertainty or ("正文重复引用同一条参考文献" if duplicates else "按完整提取文本核对引用是否重复"),
                    "正文参考文献引用", "content", "references.citation_unique")
    font_requirements = [("body.fonts." + slot, value, slot) for slot, value in body.get("fonts", {}).items()]
    if "font" in body:
        font_requirements.append(("body.font", body["font"], None))
    properties = [(target, expected, "font", slot) for target, expected, slot in font_requirements]
    if "size_pt" in body:
        properties.append(("body.size_pt", body["size_pt"], "size_pt", None))
    region = body.get("pdf_region_mm")
    font_inventory = Counter(span.get("font") or "未记录" for page in pages for span in page.get("spans", []))
    for target, expected, property_name, slot in properties:
        if not is_pdf:
            add(target, expected)
            continue
        if not region:
            add(target, expected, dict(font_inventory), "manual",
                "已提取原生字体证据，但 PDF 无法对应 Word 正文样式；需确认 body.pdf_region_mm 正文范围后按区域检测")
            continue
        matched = 0
        for page in pages:
            if page.get("method") != "text":
                add(target, expected, check_status="manual", reason="扫描/OCR 页无法证明原字体或字号", location=f"PDF第{page['number']}页")
                continue
            left, right = region["left"] * 72 / 25.4, (page["width_mm"] - region["right"]) * 72 / 25.4
            top, bottom = region["top"] * 72 / 25.4, (page["height_mm"] - region["bottom"]) * 72 / 25.4
            if left >= right or top >= bottom:
                add(target, expected, check_status="manual", reason="正文检查范围超出当前 PDF 页面", location=f"PDF第{page['number']}页")
                continue
            for span in page.get("spans", []):
                box = span.get("bbox", [])
                if len(box) != 4 or not (box[0] >= left and box[1] >= top and box[2] <= right and box[3] <= bottom):
                    continue
                if slot:
                    from .builtin import font_slots
                    if slot not in font_slots(span["text"]):
                        continue
                matched += 1
                if span.get("paint_visibility") != "painted":
                    add(target, expected, check_status="manual", reason="该文字缺少可核对的绘制状态，不能证明可见字体或字号",
                        location=span.get("location", f"PDF第{page['number']}页"))
                    continue
                actual = span.get(property_name)
                if property_name == "font":
                    observed, wanted = normalize_font_name(actual), normalize_font_name(expected)
                    status = "manual" if observed is None else "passed" if observed == wanted else "failed"
                else:
                    status = "manual" if actual is None else "passed" if abs(actual - expected) <= .1 else "failed"
                add(target, expected, actual, status, "仅检查显式选定 PDF 区域内的原生文字；不推断 Word 段落样式",
                    span.get("location", f"PDF第{page['number']}页"))
        if not matched:
            add(target, expected, check_status="manual", reason="正文区域未取得匹配文字的原生字体/字号证据")
    add("layout.visual", "人工核对最终页面或文本展示", check_status="manual", reason="分页、图表、遮挡、签章及最终打印效果仍需人工复核", rule="layout.visual_review")
    evidence = {"extraction": extraction_summary(document), "native_font_inventory": dict(font_inventory),
                "pdf_body_region_mm": region, "scope": "PDF按原始页面与明确区域核验；TXT/MD/JSON仅核验内容，不转换为DOCX"}
    return PluginResult(evidence=evidence, checks=checks)


def inspect_paired_pdf(context: AuditContext, original_text: str):
    """Parse paired PDF too, while separating text agreement from document identity."""
    try:
        pdf_path = context.pdf_path
        if pdf_path is None:
            raise ValueError("未提供配对 PDF")
        document = read_document(pdf_path, output_dir=context.output_dir / "paired-pdf")
        paired_context = AuditContext(pdf_path, context.kind, context.output_dir / "paired-pdf", context.settings,
                                      cache={"document": document})
        result = check_portable(paired_context)
        for check in result.checks:
            check["rule_id"] = "pdf." + check["rule_id"]
            check["target"] = "pdf." + check["target"]
        normalize = lambda value: "".join(value.split())
        match = bool(normalize(original_text)) and normalize(original_text) == normalize(document["text"])
        certain = match and document["complete"] and not document["requires_review"]
        result.checks.append({"rule_id": "pdf.text_agreement", "target": "pdf.text_agreement", "kind": "content",
                              "status": "passed" if certain else "manual", "expected": "可提取正文文字一致",
                              "actual": {"text_equal": match, "requires_review": document["requires_review"]},
                              "reason": "文字一致不证明版本、分页或图表完全配对；页眉页脚、阅读顺序与 OCR 差异需人工核对"})
        result.status = "completed" if document["complete"] else "incomplete"
        return result
    except (OSError, ValueError) as error:
        detail = redact_local_paths(str(error))
        return PluginResult(issues=[Issue("pdf.not_checked", "manual", "配对 PDF 未能解析，请核对原件", actual=detail)],
                            evidence={"error": detail}, checks=[{"rule_id": "pdf.read", "target": "pdf.content", "kind": "integrity",
                                      "status": "error", "reason": detail}], status="incomplete")
