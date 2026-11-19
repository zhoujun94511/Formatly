"""Field observations from an explicitly declared structured document table."""
from __future__ import annotations

from datetime import date
import re
from typing import Any, Callable


def illustrative_value(prefix: str, raw: str) -> bool:
    """An instruction or a tagged sample is not a filled value.

    A real name or organization may contain 示例 as ordinary characters.
    """
    marker = r"示例|例如|例子|填写说明|样例|example"
    if re.search(marker, prefix, re.IGNORECASE):
        return True
    text = raw.strip()
    if re.fullmatch(marker, text, re.IGNORECASE):
        return True
    return re.search(r"[（(]\s*(?:示例|例如|样例|example)\s*[）)]", text, re.IGNORECASE) is not None


def unfilled_value(value: str) -> bool:
    text = value.strip().strip("，,")
    return (not text or bool(re.fullmatch(r"[_＿—\-\s.·□]+", text))
            or text in {"待填写", "此处填写", "待补充"})


def structured_fields(document: dict[str, Any]) -> dict[str, str] | None:
    """Only the validated v1 fields object declares a structural field table."""
    fields = document.get("structured_fields")
    if (document.get("format") != "json" or document.get("json_schema") != "formatly.document.v1"
            or not isinstance(fields, dict) or any(not isinstance(value, str) for value in fields.values())):
        return None
    return fields


def merge_structured_fields(document: dict[str, Any], fields: dict[str, Any],
                            normalize: Callable[[str, str], str]) -> None:
    """Keep table omissions distinct from unparsed or conflicting body evidence.

    Omission only proves that the explicit table lacks a value. It does not
    turn a failed text-label search in an arbitrary document into an error.
    """
    declared = structured_fields(document)
    if declared is None:
        return
    certain = document.get("complete") is True and document.get("requires_review") is False
    for key, field in fields.items():
        pointer = "/fields/" + key
        raw = declared.get(key)
        missing = key not in declared
        empty = raw is not None and unfilled_value(raw)
        observation = {"pointer": pointer, "present": not missing, "value": raw}
        field["structured_observation"] = observation
        if missing or empty:
            if field["values"]:
                if empty:
                    field["status"] = "ambiguous"
                    field["review_reason"] = "结构化字段为空或占位符，但正文含字段值，须核对两处内容"
                # Explicit positive body evidence can supply an omitted key;
                # absence of the key alone must not contradict that evidence.
                continue
            if field.get("unparsed_evidence"):
                field["review_reason"] = "正文含非空字段，但日期或值格式未能可靠解释，须核对原稿"
                field["locations"] = list(dict.fromkeys(item["location"] for item in field["unparsed_evidence"]))
                continue
            field["absence_confirmed"] = certain
            field["structured_absence"] = {
                "reason": "missing_key" if missing else "empty_value",
                "json_pointer": "/fields" if missing else pointer,
                "expected_pointer": pointer, "field": key, "value": raw,
            }
            field["locations"] = ["JSON Pointer " + field["structured_absence"]["json_pointer"]]
            if not certain:
                field["review_reason"] = "结构化输入的编码或提取完整性尚未确认，字段缺失须核对原稿"
            continue
        assert raw is not None
        normalized = normalize(key, raw)
        invalid_date = False
        if key in {"start_date", "end_date"}:
            try:
                date.fromisoformat(normalized)
            except ValueError:
                invalid_date = True
        if len(raw.strip()) > 120 or invalid_date:
            field["status"] = "uncertain" if field["values"] else "missing"
            field["review_reason"] = "结构化字段非空，但日期或值格式未能可靠解释，须核对原稿"
            field["locations"] = list(dict.fromkeys([*field["locations"], "JSON Pointer " + pointer]))
            continue
        if illustrative_value("", raw):
            field.setdefault("unparsed_evidence", []).append(
                {"text": raw, "location": "JSON Pointer " + pointer, "reason": "illustrative"})
            field["status"] = "uncertain" if field["values"] else "missing"
            field["review_reason"] = "结构化字段是示例或填写说明，不能作为已填写的值"
            field["locations"] = list(dict.fromkeys([*field["locations"], "JSON Pointer " + pointer]))
            continue
        evidence = {"value": normalized, "text": raw, "location": "JSON Pointer " + pointer,
                    "method": "text", "confidence": None, "uncertain": not certain}
        field["evidence"].append(evidence)
        values = list(dict.fromkeys(item["value"] for item in field["evidence"]))
        uncertain = not certain or bool(field.get("unparsed_evidence")) or any(item["uncertain"] for item in field["evidence"])
        field.update(value=values[0] if len(values) == 1 else None, values=values,
                     status="uncertain" if uncertain else "resolved" if len(values) == 1 else "ambiguous",
                     locations=list(dict.fromkeys(item["location"] for item in
                                    [*field["evidence"], *field.get("unparsed_evidence", [])])))
