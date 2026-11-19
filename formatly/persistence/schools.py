"""Versioned school evidence and explicitly confirmed, bounded rule compilation."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from xml.etree.ElementTree import Element

from ..files import MAX_FILE_BYTES, NS, W, atomic_write, safe_child, sha256, write_json
from ..documents.ooxml import parse_on_off
from ..plugins.fields import FIELD_LABELS
from ..plugins.academic_rules import ACADEMIC_TARGETS, PARAGRAPH_PROPERTIES, TARGET_LABELS, academic_text_values, validate_academic_value
from .locks import write_lock
from .school_text import BodyTextContext, body_values, margin_values, paper_values, required_heading_values
from .school_compiler import (SCOPE_FIELDS, compile_requirement_profile, needs_binding, requirement_conflicts,
                              validate_requirement_scope)
from ..plugins.structure_rules import STRUCTURE_LABELS, validate_structure_requirement

KINDS = ("thesis", "intern", "certificate")
MAX_SCHOOL_BYTES = 8 * 1024 * 1024
MAX_TEXT = 1024 * 1024
MAX_REQUIREMENTS = 1500
MAX_CANDIDATE_LINES = 1000
PAGE_TARGETS = {"page.width_mm", "page.height_mm", *["page.margins_mm." + side for side in ("top", "bottom", "left", "right")]}
BODY_TARGETS = {"body.font", "body.size_pt", "body.line_spacing", "body.style_ids", *["body.fonts." + slot for slot in ("eastAsia", "ascii", "hAnsi", "cs")]}
REFERENCE_TARGETS = {"references.heading_after_lines", "references.entry_hanging_chars",
                     "references.citation_order", "references.citation_unique"}
AUTOMATIC_TARGETS = PAGE_TARGETS | BODY_TARGETS | REFERENCE_TARGETS | ACADEMIC_TARGETS | set(STRUCTURE_LABELS) | {"required_heading"} | {"field." + key for key in FIELD_LABELS}


class SchoolVersionConflict(ValueError):
    """The caller's school snapshot has been superseded."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _conflicts(requirements, confirmed_only=False):
    return requirement_conflicts(requirements, confirmed_only)


def _candidate(source, target, expected, label, locator, excerpt, mode="automatic", scope_style_ids=None):
    result = {"id": "req-" + uuid.uuid4().hex[:16], "kind": source["kind"], "target": target,
            "expected": expected, "label": label, "source_id": source["id"], "source_locator": locator,
            "source_excerpt": excerpt[:2000], "mode": mode, "confirmed": False, "excluded": False, "exclusion_reason": ""}
    if target in BODY_TARGETS - {"body.style_ids"} or target.startswith("paragraph."):
        result["scope_style_ids"] = list(scope_style_ids or ())
    return result


def text_candidates(source: dict[str, Any], text: str,
                    entries: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Extract explicit phrases and retain one whole-source review obligation."""
    candidates = []
    if entries is None:
        lines = [(f"文本第{index}行", line.strip()) for index, line in enumerate(text.splitlines(), 1) if line.strip()]
    else:
        lines = [(entry.get("location", "来源文本"), line.strip()) for entry in entries
                 for line in entry.get("text", "").splitlines() if line.strip()]
    context = BodyTextContext()
    headings = required_heading_values(lines[:MAX_CANDIDATE_LINES])
    # Reserve a whole-source review item and an explicit unscanned-tail item.
    # Headers and prose are evidence, not a separate requirement per line.
    candidate_budget = MAX_REQUIREMENTS - 2
    processed = 0
    for locator, line in lines[:MAX_CANDIDATE_LINES]:
        if len(candidates) >= MAX_REQUIREMENTS - 20:
            break
        processed += 1
        body_parts, body_heading = context.parts(line)
        for target, value, label in paper_values(line):
            candidates.append(_candidate(source, target, value, label, locator, line))
        remaining = candidate_budget - len(candidates)
        for target, value, label in margin_values(line, furniture=context.furniture)[:remaining]:
            candidates.append(_candidate(source, target, value, label, locator, line))
        remaining = candidate_budget - len(candidates)
        for target, value, label in body_values(body_parts)[:remaining]:
            excerpt = body_heading + "\n" + line if body_heading else line
            candidates.append(_candidate(source, target, value, label, locator, excerpt))
        remaining = candidate_budget - len(candidates)
        for target, value, label in academic_text_values(line, body_parts)[:remaining]:
            excerpt = body_heading + "\n" + line if target.startswith("paragraph.") and body_heading else line
            candidates.append(_candidate(source, target, value, label, locator, excerpt))
        # A general time requirement does not prescribe exact date labels or
        # formats. Only explicitly requested fields become presence candidates.
        proof = re.search(r"(?:实习证明|证明材料).{0,30}(?:包括|包含|注明|填写|列明|写明)", line)
        if source["kind"] == "certificate" and proof and not re.search(r"无需|不必|可不|不要求", line):
            for field, labels in FIELD_LABELS.items():
                if any(label in line[proof.start():] for label in labels):
                    candidates.append(_candidate(source, "field." + field, None, "证明明确字段候选", locator, line))
            if "实习时间" in line and not re.search(r"开始日期|起始日期|结束日期|截止日期", line):
                candidates.append(_candidate(source, "manual.internship_time", None, "按原文核对实习时间及累计时长", locator, line, "manual"))
            if re.search(r"盖.{0,6}[章印]|印章", line):
                candidates.append(_candidate(source, "manual.unit_stamp", None, "人工核对单位印章", locator, line, "manual"))
        if "参考文献" in line:
            after = re.search(r"段后(?:属性|间距|距)?[^0-9]{0,16}(?:要求|为|：|:)?\s*(\d+(?:\.\d+)?)\s*行", line)
            if after and re.search(r"参考文献.{0,12}(?:标题|章节)|(?:标题|章节).{0,12}参考文献", line):
                candidates.append(_candidate(source, "references.heading_after_lines", float(after[1]),
                                             "参考文献标题段后距候选", locator, line))
            if re.search(r"引用顺序|从小到大|递增", line) and re.search(r"第\s*1\s*条|[1１]", line):
                candidates.append(_candidate(source, "references.citation_order", "ascending",
                                             "参考文献引用顺序候选", locator, line))
            if re.search(r"不能|不得|禁止|不应", line) and re.search(r"重复引用", line):
                candidates.append(_candidate(source, "references.citation_unique", True,
                                             "参考文献不得重复引用候选", locator, line))
        if "悬挂缩进" in line and re.search(r"参考文献|文献条目|引文条目", line):
            hanging = re.search(r"悬挂缩进[^0-9]{0,16}(?:要求|为|：|:)?\s*(\d+(?:\.\d+)?)\s*字符", line)
            if hanging:
                candidates.append(_candidate(source, "references.entry_hanging_chars", float(hanging[1]),
                                             "参考文献悬挂缩进候选", locator, line))
        remaining = max(0, candidate_budget - len(candidates))
        for heading, heading_locator, excerpt in headings.get(processed - 1, [])[:remaining]:
            candidates.append(_candidate(source, "required_heading", heading, "必备独立标题候选", heading_locator, excerpt))
    if len(candidates) >= candidate_budget:
        # One dense source line can hold many explicit observations.
        candidates = candidates[:candidate_budget]
        processed = max(0, processed - 1)
    # Even a partially recognised sentence can contain additional conditions.
    # This obligation covers the entire source, never only unmatched lines.
    locator = (lines[0][0] if len(lines) == 1 else
               f"来源全文（{len(lines)}行；{lines[0][0]} 至 {lines[-1][0]}）"[:300]) if lines else "来源全文"
    candidates.append(_candidate(source, "manual.source_clause", None, "核对全文并补录候选未覆盖的要求", locator,
                                 lines[0][1] if lines else "", "manual"))
    if len(lines) > processed:
        candidates.append(_candidate(source, "manual.remaining_text", None, f"另有 {len(lines) - processed} 行原文待逐项编制规则",
                                     lines[processed][0], "全文保存在学校依据中，达到候选提取预算；其余条款须人工逐项核对", "manual"))
    return candidates


def _pdf_template_candidates(source, extraction):
    """PDF geometry is observable; dominant typography remains a candidate.

    Text bounds are not Word margins, and a visible font is not a Word style.
    We therefore do not invent those attributes from a PDF rendering.
    """
    from collections import Counter
    candidates = []
    for page in extraction.get("pages", []):
        locator = f"PDF第{page['number']}页"
        for target, key in (("page.width_mm", "width_mm"), ("page.height_mm", "height_mm")):
            value = page.get(key)
            if isinstance(value, (int, float)) and value > 0:
                candidates.append(_candidate(source, target, round(value, 3), "PDF模板实际页面尺寸候选", locator, f"{target} = {value:.3f} mm"))
        if page.get("method") != "text":
            continue  # OCR can recover text, never an original embedded font.
        spans = page.get("spans", [])
        for slot, pattern in (("eastAsia", r"[\u3400-\u9fff]"), ("ascii", r"[A-Za-z]")):
            fonts = Counter()
            sizes = Counter()
            for span in spans:
                count = len(re.findall(pattern, span.get("text", "")))
                if count:
                    if isinstance(span.get("font"), str) and span["font"].strip():
                        fonts[re.sub(r"^[A-Z]{6}\+", "", span["font"])] += count
                    if isinstance(span.get("size_pt"), (int, float)) and 1 <= span["size_pt"] <= 200:
                        sizes[round(span["size_pt"], 2)] += count
            if fonts:
                font, count = fonts.most_common(1)[0]
                if count >= sum(fonts.values()) * .6:
                    candidates.append(_candidate(source, "body.fonts." + slot, font, "PDF主要字体候选（请核对是否为正文）", locator,
                                                 f"可提取{slot}文字中主要嵌入字体：{font}；PDF不含Word正文样式定义"))
            if slot == "eastAsia" and sizes:
                size, count = sizes.most_common(1)[0]
                if count >= sum(sizes.values()) * .6:
                    candidates.append(_candidate(source, "body.size_pt", size, "PDF主要字号候选（请核对是否为正文）", locator,
                                                 f"可提取中文文字中主要字号：{size} pt；须人工确定正文适用范围"))
    return candidates


def _twips_to_mm(raw: str | None) -> float | None:
    if not raw or not re.fullmatch(r"\+?[0-9]{1,9}", raw):
        return None
    return round(int(raw) * 25.4 / 1440, 3)


def _template_paragraph_candidates(source, package, content, budget):
    """Observe body candidate styles without authorizing a manuscript range."""
    from ..documents.academic_semantics import paragraph_observation
    from ..documents.docx_scope import body_scope_roles
    from ..documents.docx_semantics import paragraph_style
    document, styles = package["document"], package.get("styles")
    candidate_styles = set() if styles is None else {
        node.get(W + "styleId") for node in styles.findall("w:style", NS)
        if node.get(W + "type") == "paragraph" and
        (parse_on_off(node.get(W + "default"), default=False) is True or node.get(W + "styleId") in {"Normal", "BodyText", "正文"})
    }
    parents = {child: parent for parent in document.iter() for child in parent}
    roles = body_scope_roles(document, styles, content.paragraphs, exclude_containers=True)
    result, seen = [], set()
    abstract_section = False
    for visible in content.paragraphs[:MAX_CANDIDATE_LINES]:
        role, role_reason = roles.get(visible.index, (None, ""))
        if role == "abstract_heading":
            abstract_section = True
        elif role in {"heading", "structural_heading"}:
            abstract_section = False
        style_id = paragraph_style(visible.element, styles)
        if not visible.text.strip() or style_id not in candidate_styles or abstract_section:
            continue
        if role not in {None, "uncertain"}:
            continue
        node: Element | None = visible.element
        inside_table = False
        while node is not None:
            if node.tag == W + "tbl":
                inside_table = True
                break
            node = parents.get(node)
        if inside_table:
            continue
        for property_name in PARAGRAPH_PROPERTIES:
            if len(result) >= budget:
                return result
            target = "paragraph." + property_name
            observation = paragraph_observation(visible, styles, property_name)
            reason = role_reason if role == "uncertain" else observation.reason
            if not reason:
                try:
                    validate_academic_value(target, observation.value)
                except ValueError:
                    reason = "实际值或单位不能作为该段落参数的确定要求"
            key = (style_id, target, json.dumps(observation.value, sort_keys=True, ensure_ascii=False), reason)
            if key in seen:
                continue
            seen.add(key)
            scope_note = f"模板观测样式 {style_id}；此ID仅表示来源位置，须另行确认待检原稿正文样式范围"
            locator = f"模板XML段{visible.index}，样式 {style_id}"
            if reason:
                result.append(_candidate(source, "manual.template_" + target, observation.value,
                    TARGET_LABELS[target] + "须人工核对", locator, scope_note + "；" + reason, "manual"))
            else:
                # A template's sample style is not proof of the manuscript's body range.
                result.append(_candidate(source, target, observation.value, TARGET_LABELS[target] + "候选（正文范围待确认）",
                    locator, scope_note + f"；观测值：{observation.value}", scope_style_ids=[]))
    return result


def template_candidates(source: dict[str, Any], package: dict[str, Any]) -> list[dict[str, Any]]:
    """Read explicit DOCX template attributes as requirements awaiting confirmation."""
    from ..documents.docx_semantics import active_sections
    from ..documents.academic_semantics import heading_level, section_observation
    candidates = []
    sections = active_sections(package["document"])
    for index, section in enumerate(sections, 1):
        size, margins = section.find("w:pgSz", NS), section.find("w:pgMar", NS)
        for target, element, attribute in [
            ("page.width_mm", size, "w"), ("page.height_mm", size, "h"),
            *[("page.margins_mm." + side, margins, side) for side in ("top", "bottom", "left", "right")],
        ]:
            raw = element.get(W + attribute) if element is not None else None
            measurement_mm = _twips_to_mm(raw)
            if measurement_mm is None or (target in {"page.width_mm", "page.height_mm"} and measurement_mm <= 0):
                continue
            candidates.append(_candidate(source, target, measurement_mm, "模板显式页面属性候选", f"模板第{index}节", f"{target} = {measurement_mm} mm"))
        for key in ("gutter_mm", "header_distance_mm", "footer_distance_mm", "columns"):
            observation = section_observation(section, key)
            if observation.value is not None and not observation.reason:
                target = "section." + key
                candidates.append(_candidate(source, target, observation.value, "模板分节设置候选", f"模板第{index}节", f"{target} = {observation.value}"))
    styles = package.get("styles")
    indexed_styles = {} if styles is None else {style.get(W + "styleId"): style for style in styles.findall("w:style", NS)}
    from ..documents.docx_semantics import read_docx_content, merged_properties, paragraph_style, effective_size_pt, effective_font_name
    content = read_docx_content(package["document"], styles, numbering=package.get("numbering"),
                                styles_reason=package.get("styles_reason", ""))
    truncated = False
    for visible in content.paragraphs:
        index, paragraph = visible.index, visible.element
        style_node = paragraph.find("w:pPr/w:pStyle", NS)
        style_id = style_node.get(W + "val", "") if style_node is not None else ""
        style = indexed_styles.get(style_id)
        outline = paragraph.find("w:pPr/w:outlineLvl", NS)
        if outline is None and style is not None:
            outline = style.find("w:pPr/w:outlineLvl", NS)
        heading_style = bool(re.fullmatch(r"(?:Heading|标题)[1-9]", style_id, re.I))
        text = visible.text.strip()
        if (heading_style or (outline is not None and outline.get(W + "val") in {str(i) for i in range(9)})) and 0 < len(text) <= 100:
            candidates.append(_candidate(source, "required_heading", text, "模板标题候选（须确认是否为必备标题）",
                                         f"模板XML段{index}，样式 {style_id or '直接大纲级别'}", text))
        level = heading_level(visible, styles)
        if level is not None and text:
            for run in visible.runs:
                if not run.text.strip():
                    continue
                props = run.properties
                value = effective_size_pt(run.text, props)
                if value is not None:
                    candidates.append(_candidate(source, f"headings.{level}.size_pt", value, "模板大纲标题字号候选", f"模板XML段{index}", f"{level}级标题 {value:g} 磅"))
                for slot in ("eastAsia", "ascii", "hAnsi", "cs"):
                    font = effective_font_name(slot, props)
                    if font is not None:
                        candidates.append(_candidate(source, f"headings.{level}.fonts.{slot}", font, "模板大纲标题字体候选", f"模板XML段{index}", f"{level}级标题 {slot}: {font}"))
                if len(candidates) >= MAX_REQUIREMENTS - 30:
                    truncated = True
                    break
        if truncated:
            break
    style_limit = MAX_REQUIREMENTS - (1 if truncated else 0)
    if styles is not None:
        for style in styles.findall("w:style", NS):
            style_id = style.get(W + "styleId", "")
            if style.get(W + "type") != "paragraph" or not (parse_on_off(style.get(W + "default"), default=False) is True or style_id in {"Normal", "BodyText", "正文"}):
                continue
            if len(candidates) >= style_limit:
                break
            props = merged_properties(styles, style_id, "rPr", styles_reason=package.get("styles_reason", ""))
            style_items = []
            for slot, value in props.get(W + "rFonts", {}).items():
                name = slot.removeprefix(W)
                if name in {"eastAsia", "ascii", "hAnsi", "cs"} and effective_font_name(name, props) is not None:
                    style_items.append(_candidate(source, "body.fonts." + name, value, "模板正文样式字体候选", "模板样式 " + style_id, value,
                                                  scope_style_ids=[style_id]))
            if W + "sz" in props or W + "szCs" in props:
                sample = "".join(item.text for item in content.paragraphs if paragraph_style(item.element, styles) == style_id)
                size = effective_size_pt(sample or "A", props)
                if size is not None:
                    style_items.append(_candidate(source, "body.size_pt", size, "模板正文样式字号候选", "模板样式 " + style_id, f"{size} pt",
                                                  scope_style_ids=[style_id]))
                else:
                    style_items.append(_candidate(source, "manual.template_size", None, "模板样式有效字号须人工核对", "模板样式 " + style_id,
                                                  "复杂文字或混合文字不能确定单一有效字号", "manual"))
            pprops = merged_properties(styles, style_id, "pPr", styles_reason=package.get("styles_reason", ""))
            spacing = pprops.get(W + "spacing", {})
            if spacing.get(W + "lineRule", "auto") == "auto" and spacing.get(W + "line"):
                raw_line = spacing[W + "line"]
                if re.fullmatch(r"\+?[0-9]{1,8}", raw_line) and int(raw_line) > 0:
                    value = int(raw_line) / 240
                    style_items.append(_candidate(source, "body.line_spacing", value, "模板正文样式自动行距候选", "模板样式 " + style_id, f"{value} 倍",
                                                  scope_style_ids=[style_id]))
            for item in style_items:
                if len(candidates) >= style_limit:
                    break
                candidates.append(item)
            else:
                continue
            break
    reserve = 1 if truncated else 30
    candidates.extend(_template_paragraph_candidates(source, package, content, max(0, MAX_REQUIREMENTS - len(candidates) - reserve)))
    for candidate in candidates:
        match = re.fullmatch(r"模板第(\d+)节", candidate["source_locator"])
        if match and candidate["target"].startswith(("page.", "section.")):
            candidate["scope_section_indices"] = [int(match[1])]
    if truncated:
        candidates.append(_candidate(
            source, "manual.remaining_text", None, "其余模板条款待逐项编制规则", "模板原件",
            "候选数量达到上限，未纳入的条款须人工核对", "manual"))
    return candidates


class SchoolStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "schools"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _directory(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"school-[a-f0-9]{16}", identity):
            raise ValueError("学校依据标识无效")
        return self.root / identity

    @staticmethod
    def _check_record_size(value):
        # Match write_json's UTF-8 representation, including indentation.
        encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_SCHOOL_BYTES:
            raise ValueError("学校依据记录将超过8MiB，未保存；请拆分学校要求组或精简来源说明")

    def _save(self, value):
        directory = self._directory(value["id"])
        value["updated_at"] = _now()
        self._check_record_size(value)
        # Revision first, pointer second. Failed publication leaves old current
        # state intact and never overwrites a historical confirmed revision.
        write_json(directory / "revisions" / f"{value['version']}.json", value)
        write_json(directory / "school.json", value)

    def list(self):
        return self.list_with_warnings()["items"]

    def list_errors(self):
        return self.list_with_warnings()["warnings"]

    def list_with_warnings(self):
        items, warnings = [], []
        for path in sorted(self.root.glob("school-*/school.json")):
            identity = path.parent.name
            try:
                items.append(self.get(identity))
            except (OSError, ValueError, KeyError):
                label = identity if re.fullmatch(r"school-[a-f0-9]{16}", identity) else "无效学校记录"
                warnings.append({"id": label, "file": label,
                                 "message": "学校依据记录损坏或不可读取；原文件已保留，请恢复备份或重新创建。"})
        return {"items": items, "warnings": warnings}

    def get(self, identity):
        path = self._directory(identity) / "school.json"
        if not path.is_file():
            raise KeyError("学校依据不存在")
        try:
            if path.stat().st_size > MAX_SCHOOL_BYTES:
                raise ValueError("学校依据记录超过8MiB，无法读取")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("学校依据记录损坏，请重新创建学校依据") from exc
        if (not isinstance(value, dict) or value.get("id") != identity
                or not isinstance(value.get("name"), str) or not value["name"].strip()
                or type(value.get("version")) is not int or value["version"] < 1
                or value.get("status") not in {"draft", "confirmed"}
                or not isinstance(value.get("sources"), list)
                or not isinstance(value.get("candidates"), list)
                or not isinstance(value.get("requirements"), list)
                or not isinstance(value.get("conflicts"), list)
                or not isinstance(value.get("profiles"), list)):
            raise ValueError("学校依据记录结构无效，请重新创建学校依据")
        return value

    def create(self, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("学校依据名称必填且最多120字符")
        value = {"id": "school-" + uuid.uuid4().hex[:16], "name": name.strip(), "version": 1, "status": "draft",
                 "created_at": _now(), "sources": [], "candidates": [], "requirements": [], "conflicts": [], "profiles": []}
        self._save(value)
        return value

    def get_draft(self, identity):
        """Read unconfirmed editing state without changing school revisions."""
        self.get(identity)
        path = self._directory(identity) / "draft.json"
        if not path.is_file():
            return {"school_id": identity, "draft_version": 0, "draft": None}
        try:
            if path.stat().st_size > MAX_SCHOOL_BYTES:
                raise ValueError("学校要求草稿超过8MiB，无法读取")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("学校要求草稿记录损坏，请重新读取") from exc
        if (not isinstance(value, dict) or value.get("school_id") != identity
                or type(value.get("draft_version")) is not int or value["draft_version"] < 0
                or (value.get("draft") is not None and not isinstance(value.get("draft"), dict))):
            raise ValueError("学校要求草稿记录损坏，请检查数据目录")
        return value

    @staticmethod
    def _draft_requirements(items):
        if not isinstance(items, list) or len(items) > MAX_REQUIREMENTS:
            raise ValueError("草稿要求须为最多1500项的数组")
        result, seen = [], set()
        fields = {"id", "kind", "target", "label", "valueText", "source_id", "source_locator", "source_excerpt",
                  "mode", "confirmed", "excluded", "exclusion_reason", *SCOPE_FIELDS}
        for item in items:
            if not isinstance(item, dict) or not set(item).issubset(fields):
                raise ValueError("草稿要求字段无效")
            identity = item.get("id")
            if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identity) or identity in seen:
                raise ValueError("草稿要求标识无效或重复")
            seen.add(identity)
            if item.get("kind") not in KINDS or item.get("mode") not in {"automatic", "manual"}:
                raise ValueError("草稿材料类型或执行方式无效")
            for key, maximum in (("target", 120), ("label", 500), ("valueText", 12000), ("source_id", 100),
                                 ("source_locator", 300), ("source_excerpt", 2000), ("exclusion_reason", 1000)):
                value = item.get(key, "") if key == "exclusion_reason" else item.get(key)
                if not isinstance(value, str) or len(value) > maximum:
                    raise ValueError(f"草稿{key}内容无效或超长")
            if type(item.get("confirmed")) is not bool or type(item.get("excluded", False)) is not bool:
                raise ValueError("草稿确认及排除状态无效")
            scope = item.get("scope_style_ids", [])
            if not isinstance(scope, list) or len(scope) > 100 or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in scope):
                raise ValueError("草稿正文样式范围无效")
            validate_requirement_scope(item, draft=True)
            # Preserve omitted optional fields: three-way merge compares draft
            # snapshots against the exact school baseline, including omissions.
            result.append(json.loads(json.dumps(item, ensure_ascii=False, allow_nan=False)))
        return result

    def save_draft(self, identity, payload):
        if not isinstance(payload, dict):
            raise ValueError("草稿须为对象")
        expected = payload.get("expected_draft_version")
        base_version = payload.get("base_school_version")
        if type(expected) is not int or expected < 0 or type(base_version) is not int or base_version < 1:
            raise ValueError("草稿及学校版本须为有效整数")
        baseline = self._draft_requirements(payload.get("baseline"))
        requirements = self._draft_requirements(payload.get("requirements"))
        conflicts = payload.get("refresh_conflicts", [])
        identities = {item["id"] for item in requirements}
        if not isinstance(conflicts, list) or len(conflicts) > MAX_REQUIREMENTS or any(not isinstance(value, str) or value not in identities for value in conflicts):
            raise ValueError("草稿冲突标识无效")
        draft = {"base_school_version": base_version, "baseline": baseline, "requirements": requirements,
                 "refresh_conflicts": list(dict.fromkeys(conflicts)), "updated_at": _now()}
        if len(json.dumps(draft, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 4 * MAX_TEXT:
            raise ValueError("草稿内容超过4MiB，请整理要求或拆分学校要求组")
        with write_lock(self.root, self._lock):
            school = self.get(identity)
            current = self.get_draft(identity)
            if current["draft_version"] != expected:
                raise SchoolVersionConflict("草稿已在其他窗口更新，请读取最新草稿后选择恢复或保留本地修改")
            if school["version"] != base_version:
                raise SchoolVersionConflict("学校要求已更新，请读取最新要求并核对本地修改后再保存草稿")
            value = {"school_id": identity, "draft_version": expected + 1, "draft": draft}
            write_json(self._directory(identity) / "draft.json", value)
            return value

    def discard_draft(self, identity, expected_draft_version):
        if type(expected_draft_version) is not int or expected_draft_version < 0:
            raise ValueError("草稿版本须为非负整数")
        with write_lock(self.root, self._lock):
            current = self.get_draft(identity)
            if current["draft_version"] != expected_draft_version:
                raise SchoolVersionConflict("草稿已在其他窗口更新，未丢弃该窗口的新修改")
            # Keep a monotonic revision after discard so an old blank window
            # cannot overwrite a new draft with an already-used version zero.
            value = {"school_id": identity, "draft_version": expected_draft_version + 1, "draft": None}
            write_json(self._directory(identity) / "draft.json", value)
            return value

    def add_source(self, identity, filename, content, kind, role, transcription=""):
        if kind not in KINDS or role not in {"template", "instructions"}:
            raise ValueError("请选择有效的材料类型与依据角色")
        if not isinstance(filename, str):
            raise ValueError("依据文件名无效")
        filename = Path(filename.replace("\\", "/")).name
        extension = Path(filename).suffix.lower()
        if not filename or len(filename) > 240 or extension not in {".docx", ".txt", ".md", ".pdf", ".json"}:
            raise ValueError("学校依据仅支持 DOCX、PDF、TXT、MD 或 JSON")
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_FILE_BYTES:
            raise ValueError("学校依据为空或超过40MB")
        if not isinstance(transcription, str) or len(transcription.encode("utf-8")) > MAX_TEXT:
            raise ValueError("转录文本超过1MiB或格式错误")
        has_transcription = bool(transcription.strip())
        if extension != ".pdf" and has_transcription:
            raise ValueError("仅 PDF 依据接受单独转录文本，其他文件直接读取原文")
        if extension == ".pdf" and not content.startswith(b"%PDF-"):
            raise ValueError("PDF 签名无效")
        with write_lock(self.root, self._lock):
            value = self.get(identity)
            if len(value["sources"]) >= 30:
                raise ValueError("每个学校依据包最多30个来源文件")
            source_id = uuid.uuid4().hex
            directory = self._directory(identity) / "sources" / source_id
            original = directory / ("original" + extension)
            try:
                atomic_write(original, content)
                from ..documents import read_document
                # Verified text replaces OCR, while native reading still checks
                # the original PDF and preserves its own completeness evidence.
                document = read_document(original, output_dir=directory / "extraction", ocr=not has_transcription)
                extracted_text = document["text"]
                text = transcription if has_transcription else extracted_text
                methods = {entry.get("method", "text") for entry in document["entries"]}
                text_method = "mixed" if methods == {"text", "ocr"} else "ocr" if "ocr" in methods else "extracted"
                status = "partial" if not document.get("complete", True) else "ocr" if "ocr" in methods else "extracted"
                warnings = [*document.get("warnings", []), "候选提取不等于学校规则已确认；全文及适用范围仍需审核"]
                entries = document["entries"]
                if has_transcription:
                    status, text_method = "transcribed", "transcription"
                    warnings.append("当前规则候选使用人工转录覆盖；自动读取未启用OCR，原始提取完整性与证据仍保留，转录范围须与PDF原件核对")
                    entries = [{"text": line, "location": f"人工转录第{index}行（对应PDF页码请核对）", "method": "transcription"}
                               for index, line in enumerate(text.splitlines(), 1) if line.strip()]
                if len(text.encode("utf-8")) > MAX_TEXT:
                    raise ValueError("提取文本超过1MiB，请拆分学校说明文件")
                extraction = {key: item for key, item in document.items() if key != "docx"}
                write_json(directory / "extraction.json", extraction)
                atomic_write(directory / "extracted.txt", extracted_text.encode("utf-8"))
                extraction_summary = {"format": document["format"], "complete": document.get("complete", True),
                                      "requires_review": document.get("requires_review", False), "warnings": document.get("warnings", []),
                                      "page_count": document.get("page_count", len(document.get("pages", []))),
                                      "processed_pages": document.get("processed_pages", len(document.get("pages", []))),
                                      "pages": [{key: page[key] for key in ("number", "width_mm", "height_mm", "method") if key in page}
                                                for page in document.get("pages", [])]}
                if "ocr" in document:
                    extraction_summary["ocr"] = document["ocr"]
                source = {"id": source_id, "filename": filename, "kind": kind, "role": role, "sha256": sha256(original),
                          "size": len(content), "path": original.relative_to(self._directory(identity)).as_posix(),
                          "text": text, "extraction_status": status, "parse_status": status,
                          "text_method": text_method, "extraction": extraction_summary,
                          "extraction_sha256": sha256(directory / "extraction.json"),
                          "extracted_text_sha256": sha256(directory / "extracted.txt"),
                          "warnings": warnings, "created_at": _now()}
                if has_transcription:
                    atomic_write(directory / "transcription.txt", transcription.encode("utf-8"))
                    source["transcription_sha256"] = sha256(directory / "transcription.txt")
                atomic_write(directory / "text.txt", text.encode("utf-8"))
                source["text_sha256"] = sha256(directory / "text.txt")
                candidates = text_candidates(source, text, entries if extension in {".pdf", ".json"} else None)
                if role == "template":
                    if "docx" in document:
                        candidates = template_candidates(source, document["docx"]) + candidates
                    elif extension == ".pdf":
                        candidates = _pdf_template_candidates(source, document) + candidates
                if document.get("requires_review") or not document.get("complete", True):
                    candidates.append(_candidate(source, "manual.source_extraction", None,
                                                 "来源含OCR或未完整提取，须对照原件核验全部要求", "来源原件及提取记录",
                                                 "；".join(document.get("warnings", [])) or "自动提取不能替代对原件的完整审核", "manual"))
                if not candidates:
                    candidates.append(_candidate(source, "manual.source_review", None, "依据尚无可执行规则，请转录并编制要求",
                                                 "来源原件", "该来源未生成可自动执行的规则", "manual"))
                room = MAX_REQUIREMENTS - len(value["candidates"])
                if len(candidates) > room:
                    if room < 1:
                        raise ValueError("候选要求超过1500项，请拆分依据包或整理学校条款")
                    candidates = candidates[:room - 1]
                    candidates.append(_candidate(
                        source, "manual.remaining_text", None, "其余条款待逐项编制规则", "来源原件",
                        "候选数量达到上限，未纳入的条款须人工核对", "manual"))
                source["candidate_count"] = len(candidates)
                value["sources"].append(source)
                value["candidates"].extend(candidates)
                value["status"] = "draft"
                value["version"] += 1
                value["conflicts"] = _conflicts(value["candidates"])
                self._save(value)
                return value
            except Exception:
                if directory.exists():
                    if not directory.resolve().is_relative_to(self._directory(identity).resolve()) or directory.is_symlink():
                        raise RuntimeError("拒绝清理学校依据目录外的路径")
                    shutil.rmtree(directory)
                raise

    def source(self, identity, source_id):
        value = self.get(identity)
        source = next((source for source in value["sources"] if source["id"] == source_id), None)
        if source is None:
            raise KeyError("学校依据来源不存在")
        path = safe_child(self._directory(identity), source["path"])
        if not path.is_file() or sha256(path) != source["sha256"]:
            raise ValueError("学校依据原件缺失或哈希已变化")
        text_path = path.parent / "text.txt"
        expected_text = source.get("text_sha256")
        metadata_text = source.get("text")
        if (not isinstance(metadata_text, str) or not isinstance(expected_text, str) or not text_path.is_file()
                or sha256(text_path) != expected_text
                or hashlib.sha256(metadata_text.encode("utf-8")).hexdigest() != expected_text):
            raise ValueError("学校依据提取/转录文本缺失或哈希已变化，请重新导入并确认")
        # Older saved evidence has only text.txt; verify all additional artifacts
        # whenever this source version records them, without rewriting history.
        for filename, key in (("extracted.txt", "extracted_text_sha256"), ("extraction.json", "extraction_sha256"),
                              ("transcription.txt", "transcription_sha256")):
            if key in source:
                artifact = path.parent / filename
                if not artifact.is_file() or sha256(artifact) != source[key]:
                    raise ValueError("学校依据自动提取或转录证据缺失/哈希已变化，请重新导入并确认")
        return path

    def source_styles(self, identity, source_id, query="", offset=0, limit=20):
        from ..documents.style_catalog import paragraph_style_catalog
        from ..files import read_docx

        path = self.source(identity, source_id)
        if path.suffix.lower() != ".docx":
            raise ValueError("只有 DOCX 来源提供段落样式目录")
        digest = sha256(path)
        catalog = paragraph_style_catalog(read_docx(path), query, offset, limit)
        self.source(identity, source_id)
        if sha256(path) != digest:
            raise ValueError("读取样式期间来源文件发生变化，请重新导入")
        return {"school_id": identity, "source_id": source_id, "source_sha256": digest, **catalog}

    def source_context(self, identity, source_id, locator="", excerpt=""):
        from .school_review import source_context

        path = self.source(identity, source_id)
        source = next(item for item in self.get(identity)["sources"] if item["id"] == source_id)
        extraction_path = path.parent / "extraction.json"
        extraction = json.loads(extraction_path.read_text(encoding="utf-8")) if source.get("extraction_sha256") else {}
        # The effective text may be a verified transcription. Its line scope
        # cannot borrow coordinates from the original automatic extraction.
        entries = extraction.get("entries", []) if not source.get("transcription_sha256") else []
        context = source_context(source["text"], entries, locator, excerpt)
        self.source(identity, source_id)
        return {"school_id": identity, "source_id": source_id, "source_sha256": source["sha256"],
                "text_sha256": source["text_sha256"], **context}

    def confirm(self, identity, requirements, validate_profile=None, expected_version=None, publish_profiles=None):
        from .profiles import validate_profile as validate
        from .profiles import validate_style_ids
        validate = validate_profile or validate
        if not isinstance(requirements, list) or not requirements or len(requirements) > MAX_REQUIREMENTS:
            raise ValueError("请提交1至1500项学校要求")
        with write_lock(self.root, self._lock):
            value = self.get(identity)
            if expected_version is not None:
                if type(expected_version) is not int or expected_version < 1:
                    raise ValueError("expected_version 须为学校依据包的正整数版本")
                retry = (value["status"] == "confirmed" and value["version"] == expected_version + 1)
                if value["version"] != expected_version and not retry:
                    raise SchoolVersionConflict("学校要求已更新，请刷新并核对本地修改后再确认")
            sources = {source["id"]: source for source in value["sources"]}
            if not sources:
                raise ValueError("学校依据包尚无来源文件")
            for source_id in sources:
                self.source(identity, source_id)
            normalized, seen = [], set()
            for item in requirements:
                if not isinstance(item, dict):
                    raise ValueError("要求项须为对象")
                source = sources.get(item.get("source_id"))
                if source is None or item.get("kind") != source["kind"]:
                    raise ValueError("要求项必须关联同类型的真实来源")
                req_id = item.get("id")
                if not isinstance(req_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", req_id) or req_id in seen:
                    raise ValueError("要求标识无效或重复")
                mode, target = item.get("mode"), item.get("target")
                if mode not in {"automatic", "manual"} or not isinstance(target, str) or not target.strip() or len(target) > 120:
                    raise ValueError("要求的执行方式或目标无效")
                if mode == "automatic" and target not in AUTOMATIC_TARGETS:
                    raise ValueError("该要求没有自动检查能力，请改为人工复核")
                if mode == "automatic" and item.get("confirmed") and not item.get("excluded") and target in ACADEMIC_TARGETS:
                    validate_academic_value(target, item.get("expected"))
                if mode == "automatic" and item.get("confirmed") and not item.get("excluded") and target in STRUCTURE_LABELS:
                    validate_structure_requirement(target, item.get("expected"), item.get("parameters"))
                if type(item.get("confirmed")) is not bool:
                    raise ValueError("要求项须明确是否已确认")
                excluded, exclusion_reason = item.get("excluded", False), item.get("exclusion_reason", "")
                if type(excluded) is not bool or not isinstance(exclusion_reason, str) or len(exclusion_reason) > 1000:
                    raise ValueError("条款排除状态或理由无效")
                if excluded and (not item["confirmed"] or not exclusion_reason.strip()):
                    raise ValueError("排除条款须确认并填写非空理由，来源仍会保留")
                for key, maximum in (("label", 500), ("source_locator", 300), ("source_excerpt", 2000)):
                    if not isinstance(item.get(key, ""), str) or len(item.get(key, "")) > maximum:
                        raise ValueError("要求说明或来源定位过长")
                if not item.get("label", "").strip():
                    raise ValueError("要求说明必填")
                if len(json.dumps(item.get("expected"), allow_nan=False)) > 4000:
                    raise ValueError("要求预期值过长")
                if target == "body.style_ids" and mode == "automatic" and item["confirmed"] and not excluded:
                    item = {**item, "expected": validate_style_ids(item.get("expected"), allow_empty=False)}
                requirement: dict[str, Any] = {
                    **{key: item.get(key) for key in ("id", "kind", "target", "expected", "label", "source_id", "source_locator", "source_excerpt", "mode", "confirmed")},
                    "excluded": excluded,
                    "exclusion_reason": exclusion_reason.strip(),
                }
                if "scope_style_ids" in item:
                    requirement["scope_style_ids"] = validate_style_ids(item["scope_style_ids"])
                for field in SCOPE_FIELDS:
                    if field in item:
                        requirement[field] = json.loads(json.dumps(item[field], allow_nan=False))
                validate_requirement_scope(requirement)
                if needs_binding(requirement):
                    requirement["source_scope_style_ids"] = list(requirement.get("scope_style_ids", requirement.get("parameters", {}).get("style_ids", [])))
                    requirement["source_scope_section_indices"] = list(requirement.get("scope_section_indices", requirement.get("parameters", {}).get("section_indices", [])))
                    requirement["source_parameters"] = requirement.get("parameters", {}).copy()
                    requirement["scope_binding_status"] = "unbound"
                elif target.startswith(("page.", "section.")):
                    # Empty section selectors explicitly apply to the whole manuscript.
                    # Keep the template selectors as history, not as an execution lock.
                    requirement.pop("scope_binding_status", None)
                normalized.append(requirement)
                seen.add(req_id)
            # API clients cannot accidentally remove an unreviewed extracted
            # clause merely by submitting only the rules they understood.
            retained = {item["id"]: item for item in value.get("requirements", [])}
            for item in value["candidates"]:
                retained.setdefault(item["id"], item)
            normalized.extend(item for req_id, item in retained.items() if req_id not in seen)
            if len(normalized) > MAX_REQUIREMENTS:
                raise ValueError("合并未审核候选后要求超过1500项")
            for item in normalized:
                if item["target"] == "body.style_ids" and item.get("confirmed") and item["mode"] == "automatic" and not item.get("excluded"):
                    item["expected"] = validate_style_ids(item["expected"], allow_empty=False)
                if "scope_style_ids" in item:
                    item["scope_style_ids"] = validate_style_ids(item["scope_style_ids"])
            conflicts = _conflicts(normalized, confirmed_only=True)
            if conflicts:
                raise ValueError("已确认的自动规则存在冲突，请明确选用值并将其他条款保留人工复核：" + ", ".join(item["target"] for item in conflicts))
            confirmed_kinds = {item["kind"] for item in normalized if item["confirmed"] and not item.get("excluded")}
            if not confirmed_kinds:
                raise ValueError("至少确认一项未排除的学校要求后才能生成方案")
            if expected_version is not None and value["version"] != expected_version:
                publication = self._directory(identity) / "publications" / f"{value['version']}.json"
                if not publication.is_file():
                    raise SchoolVersionConflict("学校要求已更新，请刷新并核对本地修改后再确认")
                if publication.stat().st_size > 8 * MAX_SCHOOL_BYTES:
                    raise ValueError("学校方案发布记录过大，请恢复备份")
                published = json.loads(publication.read_text(encoding="utf-8"))
                if (not isinstance(published, dict) or not isinstance(published.get("profiles"), list)
                        or not 1 <= len(published["profiles"]) <= 3
                        or any(not isinstance(item, dict) for item in published["profiles"])):
                    raise ValueError("学校方案发布记录损坏，请恢复备份")
                if requirements != published.get("submitted_requirements"):
                    raise SchoolVersionConflict("学校要求已更新，请刷新并核对本地修改后再确认")
                profiles = [validate(profile) for profile in published["profiles"]]
                if [profile["id"] for profile in profiles] != value["profiles"]:
                    raise ValueError("学校方案发布记录不一致，请恢复备份")
                if publish_profiles is not None:
                    publish_profiles(profiles)
                return profiles
            version = value["version"] + 1
            profiles = []
            for kind in dict.fromkeys(source["kind"] for source in value["sources"] if source["kind"] in confirmed_kinds):
                relevant = [item for item in normalized if item["kind"] == kind]
                settings = {}
                active = [item for item in relevant if item["confirmed"] and not item.get("excluded") and item["mode"] == "automatic"]
                explicit_styles = next((validate_style_ids(item["expected"], allow_empty=False)
                                        for item in active if item["target"] == "body.style_ids"), [])
                property_scopes = {}
                paragraph_scopes = {}
                for requirement in relevant:
                    if not requirement["confirmed"] or requirement.get("excluded") or requirement["mode"] != "automatic":
                        continue
                    target, expected = requirement["target"], requirement["expected"]
                    if target in BODY_TARGETS - {"body.style_ids"}:
                        scope = requirement.get("scope_style_ids") or explicit_styles
                        requirement["scope_style_ids"] = list(scope)
                        key = target.removeprefix("body.")
                        property_scopes.setdefault(key, [])
                        property_scopes[key] = list(dict.fromkeys([*property_scopes[key], *scope]))
                    if target.startswith("paragraph."):
                        scope = requirement.get("scope_style_ids") or explicit_styles
                        requirement["scope_style_ids"] = list(scope)
                        key = target.removeprefix("paragraph.")
                        paragraph_scopes.setdefault(key, [])
                        paragraph_scopes[key] = list(dict.fromkeys([*paragraph_scopes[key], *scope]))
                    if target == "required_heading":
                        if not isinstance(expected, str) or not expected.strip():
                            raise ValueError("必备标题须为非空文本")
                        settings.setdefault("required_headings", []).append(expected)
                    elif target.startswith("field."):
                        field = target.removeprefix("field.")
                        fields = settings.setdefault("fields", {"required": [], "expected": {}})
                        fields["required"].append(field)
                        if expected is not None:
                            fields["expected"][field] = expected
                    else:
                        current = settings
                        parts = target.split(".")
                        for part in parts[:-1]:
                            current = current.setdefault(part, {})
                        current[parts[-1]] = expected
                if property_scopes:
                    body_settings = settings.setdefault("body", {})
                    body_settings["property_style_ids"] = property_scopes
                    body_settings["style_ids"] = sorted({*explicit_styles, *[style for scope in property_scopes.values() for style in scope]})
                if "required_headings" in settings:
                    settings["required_headings"] = list(dict.fromkeys(settings["required_headings"]))
                if paragraph_scopes:
                    settings.setdefault("paragraph", {}).update(
                        property_style_ids=paragraph_scopes,
                        style_ids=sorted({style for scope in paragraph_scopes.values() for style in scope}))
                if "fields" in settings:
                    settings["fields"]["required"] = list(dict.fromkeys(settings["fields"]["required"]))
                if kind == "certificate":
                    settings.setdefault("fields", {})["review_signatures"] = True
                profile = {"id": f"{identity}-v{version}-{kind}", "version": version, "name": value["name"][:100] + " · " + {"thesis": "论文", "intern": "实习报告", "certificate": "实习证明"}[kind],
                           "description": ("基于本地学校依据与已确认要求；未审核或人工条款保留复核，不代表学校最终认可。" if active else
                                           "仅包含已确认的人工复核要求；未审核条款仍保留待确认，不代表学校最终认可。"),
                           "plugins": ["docx-package", "generic-format", *(["academic-format"] if any(item["target"] in ACADEMIC_TARGETS for item in active) else []), "document-fields"], "settings": settings, "kinds": [kind],
                           "requirements": relevant, "school": {"id": identity, "name": value["name"], "version": version,
                           "sources": [{key: source[key] for key in ("id", "filename", "kind", "role", "sha256", "text_sha256",
                                        "extracted_text_sha256", "extraction_sha256", "transcription_sha256", "text_method", "parse_status") if key in source}
                                       for source in value["sources"] if source["kind"] == kind]}}
                profiles.append(validate(compile_requirement_profile(profile, kind)))
            value.update(version=version, status="confirmed", requirements=normalized, conflicts=_conflicts(normalized),
                         profiles=[profile["id"] for profile in profiles], updated_at=_now())
            # Validate the complete school record before publishing any profile
            # files; the prior revision remains usable if the new one is full.
            self._check_record_size(value)
            if publish_profiles is not None:
                # An intent precedes every profile file. Readers hide these
                # files until the school pointer commits the complete batch.
                write_json(self._directory(identity) / "publications" / f"{version}.json",
                           {"school_id": identity, "version": version, "profiles": profiles,
                            "submitted_requirements": requirements})
                publish_profiles(profiles)
            self._save(value)
            return profiles
