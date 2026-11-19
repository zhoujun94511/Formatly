"""Explicit document fields; missing and ambiguous values are never matches."""
from __future__ import annotations

import re

from ..domain import AuditContext, Issue, PluginResult
from ..files import sha256, write_json
from .labelled_fields import (
    empty_label_evidence,
    label_pattern,
    labelled_lines,
    merge_labelled_absence,
)
from .structured_fields import (
    illustrative_value,
    merge_structured_fields,
    structured_fields,
    unfilled_value,
)

FIELD_LABELS = {
    "name": ("学生姓名", "实习生姓名", "姓名"),
    "student_id": ("学生学号", "学号"),
    "organization": ("实习单位名称", "实习单位", "单位名称", "工作单位"),
    "start_date": ("实习开始日期", "开始日期", "起始日期"),
    "end_date": ("实习结束日期", "结束日期", "截止日期"),
}
_LABEL_CHOICE = "|".join(
    label_pattern(label)
    for label in sorted({label for labels in FIELD_LABELS.values() for label in labels}, key=len, reverse=True)
)
# The variable holds several labels. The groups keep the colon attached to every label;
# the checker only sees one interpolated token and would otherwise call the groups redundant.
# noinspection RegExpUnnecessaryNonCapturingGroup
_PRIOR_LABELLED_VALUE = re.compile(
    rf"(?:{_LABEL_CHOICE})\s*[：:][ \t]*.*?(?=\s*(?:{_LABEL_CHOICE})\s*[：:]|[；;\n]|$)"
)


def _instruction_prefix(prefix: str) -> str:
    """A filled label is not an instruction for the next field on the same line."""
    return _PRIOR_LABELLED_VALUE.sub(" ", prefix)


def normalize_field(field: str, value: str) -> str:
    value = re.sub(r"\s+", "", value).strip("：:")
    if field in {"start_date", "end_date"}:
        match = re.fullmatch(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?", value)
        if match:
            from datetime import date
            try:
                return date(*(int(part) for part in match.groups())).isoformat()
            except ValueError:
                return value
    return value


def extract_fields(document, styles=None) -> dict:
    """Match XML paragraphs using the shared document field rules."""
    from ..documents import docx_entries
    from ..documents.docx_semantics import read_docx_content
    content = read_docx_content(document, styles)
    return extract_entries(docx_entries(document, content=content), complete=not content.requires_review)


def extract_entries(entries, *, complete=True) -> dict:
    """Match explicit labels, preserving OCR/partial evidence as uncertain.

    Plain text and Markdown have no Word properties; only visible labels are
    interpreted. An OCR match is useful evidence, but never a certain identity.
    """
    lines = labelled_lines(entries, {label for variants in FIELD_LABELS.values() for label in variants})
    empty = empty_label_evidence(lines, FIELD_LABELS)
    all_labels = sorted({label for labels in FIELD_LABELS.values() for label in labels}, key=len, reverse=True)
    stop = "|".join(label_pattern(label) for label in all_labels)
    result = {}
    for field, labels in FIELD_LABELS.items():
        matches = []
        unparsed = []
        for text, entry in lines:
            location = entry.get("location", "文本")
            for label in labels:
                pattern = rf"(?:^|[\s；;，,]){label_pattern(label)}\s*[：:][ \t]*(.*?)(?=\s*(?:{stop})\s*[：:]|[；;\n]|$)"
                for match in re.finditer(pattern, text):
                    raw = match.group(1).strip().strip("，,")
                    if unfilled_value(raw):
                        continue
                    if illustrative_value(_instruction_prefix(text[:match.start()]), raw):
                        unparsed.append({"text": raw, "location": location, "reason": "illustrative"})
                        continue
                    if len(raw) > 120:
                        unparsed.append({"text": raw, "location": location, "reason": "value_too_long"})
                        continue
                    normalized = normalize_field(field, raw)
                    if field in {"start_date", "end_date"}:
                        from datetime import date
                        try:
                            date.fromisoformat(normalized)
                        except ValueError:
                            unparsed.append({"text": raw, "location": location, "reason": "invalid_date"})
                            continue
                    method = entry.get("method", "text")
                    confidence = entry.get("confidence")
                    uncertain = method == "ocr" or (isinstance(confidence, (int, float)) and confidence < 80)
                    matches.append({"value": normalized, "text": raw, "location": location, "method": method,
                                    "confidence": confidence, "uncertain": uncertain})
        values = list(dict.fromkeys(item["value"] for item in matches))
        uncertain = not complete or bool(unparsed) or any(item["uncertain"] for item in matches)
        result[field] = {"value": values[0] if len(values) == 1 else None, "values": values,
                         "status": "uncertain" if values and uncertain else "resolved" if len(values) == 1 else "ambiguous" if values else "missing",
                         "locations": list(dict.fromkeys(item["location"] for item in [*matches, *unparsed])), "evidence": matches}
        if unparsed:
            result[field]["unparsed_evidence"] = unparsed
            result[field]["review_reason"] = "同一字段含未能可靠解释的非空值，须核对各处内容"
        if empty[field]:
            result[field]["empty_evidence"] = empty[field]
    return result


def _empty_value_locator(document: dict, evidence: dict, input_digest: str) -> dict | None:
    """Bind a visible empty label to an existing node of the input snapshot."""
    package = document.get("docx")
    observations = evidence.get("empty_evidence")
    if not package or not observations:
        return None
    from ..documents.docx_locations import DocxLocations
    from ..files import NS
    first = observations[0]
    xml = package["document"]
    node = None
    if "docx_paragraph" in first:
        node = next((paragraph.element for paragraph in package["content"].paragraphs
                     if paragraph.index == first["docx_paragraph"]), None)
    elif "docx_table_row" in first:
        rows = xml.findall(".//w:tr", NS)
        row_index = first["docx_table_row"] - 1
        if 0 <= row_index < len(rows):
            node = rows[row_index]
    return DocxLocations(xml, input_digest).locate(node) if node is not None else None


class DocumentFieldsPlugin:
    id = "document-fields"
    name = "材料字段与证明预检"
    description = "提取有标签的姓名、学号、单位和实习起止日期，核对明确字段要求；不认证签字、印章或材料真实性。"
    settings_keys = ("fields",)
    formats = ("docx", "pdf", "txt", "md", "json")

    @staticmethod
    def probe():
        return True, "读取 DOCX、PDF、TXT、MD、JSON 的明确标签字段；OCR 识别值保留复核"

    @staticmethod
    def validate_settings(settings):
        options = settings.get("fields", {})
        if not isinstance(options, dict) or set(options) - {"required", "expected", "review_signatures", "missing_policy"}:
            raise ValueError("fields 仅支持 required、expected、review_signatures、missing_policy")
        if options.get("missing_policy", "review") not in ("review", "fail_when_complete"):
            raise ValueError("fields.missing_policy 须为 review 或 fail_when_complete")
        required, expected = options.get("required", []), options.get("expected", {})
        if not isinstance(required, list) or any(not isinstance(key, str) or key not in FIELD_LABELS for key in required):
            raise ValueError("fields.required 包含不支持的字段")
        if not isinstance(expected, dict) or any(key not in FIELD_LABELS for key in expected):
            raise ValueError("fields.expected 包含不支持的字段")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 120 for value in expected.values()):
            raise ValueError("fields.expected 须为非空文本且每项最多120字符")
        if "review_signatures" in options and type(options["review_signatures"]) is not bool:
            raise ValueError("fields.review_signatures 须为布尔值")

    def run(self, context: AuditContext):
        self.validate_settings(context.settings)
        options = context.settings.get("fields", {})
        from ..documents import read_document
        document = context.cache.get("document") or read_document(context.input_path, output_dir=context.output_dir / "document")
        context.cache["document"] = document
        if document["format"] == "md":
            from ..documents.markdown import visible_text
            markdown = visible_text(document.get("text", ""))
            document = {**document, "entries": markdown.entries,
                        "requires_review": document.get("requires_review", False) or markdown.requires_review}
        declared = structured_fields(document)
        entries = document["entries"]
        if declared is not None:
            entries = [entry for entry in entries if not (entry.get("field") in declared
                       and entry.get("location") == "JSON Pointer /fields/" + entry["field"])]
        fields = extract_entries(entries, complete=document.get("complete", True) and not document.get("requires_review", False))
        merge_structured_fields(document, fields, normalize_field)
        merge_labelled_absence(document, fields, {key: field.get("empty_evidence", []) for key, field in fields.items()},
                               options.get("missing_policy", "review"), FIELD_LABELS)
        context.cache["document_fields"] = fields
        input_digest = sha256(context.input_path)
        issues, checks = [], []
        for key in dict.fromkeys([*options.get("required", []), *options.get("expected", {})]):
            evidence = fields[key]
            expected = options.get("expected", {}).get(key)
            actual = evidence["value"]
            observed = actual if actual is not None else evidence["values"]
            expected_value = expected if expected is not None else "明确且唯一的字段值"
            location = "；".join(evidence["locations"]) or "原稿的显式标签字段"
            if evidence.get("absence_confirmed"):
                status = "failed"
                observed = evidence.get("structured_absence") or evidence["native_absence"]
                message = ("结构化字段表缺少必填字段" if observed["reason"] == "missing_key" else
                           "必填标签表单缺少字段标签" if observed["reason"] == "missing_label" else
                           "必填字段为空或仍为占位符")
                issues.append(Issue(f"field.{key}", "error", message, location, expected_value, observed))
            elif evidence["status"] != "resolved":
                status = "manual"
                observed = evidence["values"]
                if "structured_observation" in evidence:
                    observed = {"values": evidence["values"], "structured_observation": evidence["structured_observation"],
                                **({"unparsed_evidence": evidence["unparsed_evidence"]} if evidence.get("unparsed_evidence") else {})}
                if "native_observation" in evidence or "empty_evidence" in evidence or evidence.get("unparsed_evidence"):
                    observed = {"values": evidence["values"],
                                **({"structured_observation": evidence["structured_observation"]} if "structured_observation" in evidence else {}),
                                **({"native_observation": evidence["native_observation"]} if "native_observation" in evidence else {}),
                                **({"empty_evidence": evidence["empty_evidence"]} if evidence.get("empty_evidence") else {}),
                                **({"unparsed_evidence": evidence["unparsed_evidence"]} if evidence.get("unparsed_evidence") else {})}
                message = evidence.get("review_reason") or (
                    "字段来自 OCR、低置信度或不完整提取，须核对原稿" if evidence["status"] == "uncertain" else
                    "未提取到唯一字段值，须核对原稿" if evidence["status"] == "ambiguous" else "未找到明确字段值，须核对原稿")
                issues.append(Issue(f"field.{key}", "manual", message, location, expected_value, observed))
            elif expected is not None and normalize_field(key, expected) != actual:
                status = "failed"
                issues.append(Issue(f"field.{key}", "error", "材料字段与确认要求不一致", location, expected, actual))
            else:
                status = "passed"
            locator = _empty_value_locator(document, evidence, input_digest)
            checks.append({"rule_id": f"field.{key}", "target": f"field.{key}", "kind": "content", "status": status,
                           "location": location, "expected": expected_value,
                           "actual": observed, "source": "已确认字段要求", **({"locator": locator} if locator else {})})
        start, end = fields["start_date"]["value"], fields["end_date"]["value"]
        if start is not None and end is not None:
            dates_certain = all(fields[key]["status"] == "resolved" for key in ("start_date", "end_date"))
            valid_order = start <= end
            checks.append({"rule_id": "field.date_order", "target": "field.date_order", "kind": "content",
                           "status": "manual" if not dates_certain else "passed" if valid_order else "failed", "location": "实习起止日期字段",
                           "expected": "开始日期不晚于结束日期", "actual": {"start_date": start, "end_date": end}, "source": "日期先后关系",
                           "reason": "两项日期均为完整原生文本证据" if dates_certain else "日期来自OCR、低置信度或不完整提取，顺序须核对原稿"})
            if not dates_certain:
                issues.append(Issue("field.date_order", "manual", "日期来自OCR、低置信度或不完整提取，顺序须核对原稿", "实习起止日期字段",
                                    "已核实的起止日期", {"start_date": start, "end_date": end}, "日期先后关系"))
            elif not valid_order:
                issues.append(Issue("field.date_order", "error", "实习开始日期晚于结束日期", "实习起止日期字段",
                                    "开始日期不晚于结束日期", {"start_date": start, "end_date": end}, "日期先后关系"))
        if context.kind == "certificate" or options.get("review_signatures"):
            message = "签字、盖章、证明授权和材料真实性需人工核验，本工具不出具真实性认证"
            issues.append(Issue("certificate.authorization", "manual", message, source="材料审核范围"))
            checks.append({"rule_id": "certificate.authorization", "target": "certificate.authorization", "kind": "content",
                           "status": "manual", "location": "证明原件", "expected": "有效签字盖章与授权", "actual": None, "source": "材料审核范围"})
        evidence = {"fields": fields, "format": document["format"], "complete": document.get("complete", True),
                    "input_sha256": input_digest, "input_filename": context.input_path.name,
                    "requires_review": document.get("requires_review", False), "warnings": document.get("warnings", []),
                    "field_text_coverage": document.get("field_text_coverage"), "missing_policy": options.get("missing_policy", "review"),
                    "scope": "显式标签及结构化JSON字段表；完整原生文本明确空值可失败，缺标签按所选表单契约核对；OCR和不完整范围保留复核，不认证签字盖章"}
        write_json(context.output_dir / self.id / "fields.json", evidence)
        return PluginResult(issues=issues, evidence=evidence, checks=checks)
