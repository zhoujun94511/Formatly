"""Empty labelled values and explicitly selected complete-form requirements."""
from __future__ import annotations

import re

from ..documents.field_coverage import field_text_coverage
from .structured_fields import unfilled_value


def compact_label(value: str) -> str:
    """Compare labels while allowing Word forms such as ``姓 名``."""
    return re.sub(r"\s+", "", value)


def label_pattern(label: str) -> str:
    """Match optional whitespace between characters without changing values."""
    return r"\s*".join(re.escape(character) for character in label)


def labelled_lines(entries, labels: set[str]) -> list[tuple[str, dict]]:
    """Preserve source locations while exposing adjacent Markdown cells."""
    original = []
    for entry in entries:
        for raw in entry.get("text", "").splitlines():
            text = re.sub(r"^\s*#{1,6}\s+", "", raw.strip())
            text = re.sub(r"([*`]{1,3})(.+?)\1", r"\2", text)
            if text:
                original.append((text, entry))
    result = []
    for index, (text, entry) in enumerate(original):
        following = original[index + 1][0] if index + 1 < len(original) else ""
        compact_labels = {compact_label(label) for label in labels}
        if entry.get("table_pair") and compact_label(entry.get("table_value", "").rstrip("：:").strip()) in compact_labels:
            text = entry.get("table_label", text).rstrip("：:").strip()
        is_table = text.startswith("|") and text.endswith("|")
        if not is_table:
            result.append((text, {**entry, "following_text": following}))
        if not is_table:
            continue
        cells = [cell.strip() for cell in text.strip("|").split("|")]
        for cell_index, cell in enumerate(cells):
            if any(re.match(rf"^{label_pattern(label)}\s*[：:]\s*\S", cell) for label in labels):
                result.append((cell, {**entry, "following_text": "", "table_pair": True}))
            label = cell.rstrip("：:").strip()
            if compact_label(label) in compact_labels and (cell_index + 1 == len(cells) or compact_label(cells[cell_index + 1].rstrip("：:").strip()) in compact_labels):
                result.append((label, {**entry, "following_text": "", "table_pair": True}))
        for cell_index in range(len(cells) - 1):
            label = cells[cell_index].rstrip("：:").strip()
            value = cells[cell_index + 1]
            if compact_label(label) in compact_labels and compact_label(value.rstrip("：:").strip()) not in compact_labels:
                result.append((label + "：" + value, {**entry, "following_text": "", "table_pair": True}))
    return result


def empty_label_evidence(lines, labels: dict[str, tuple[str, ...]]) -> dict[str, list[dict]]:
    """Recognize real empty labels without consuming the next field as a value."""
    all_labels = sorted({label for variants in labels.values() for label in variants}, key=len, reverse=True)
    alternatives = "|".join(label_pattern(label) for label in all_labels)
    # Every label variant shares the boundary; keep the choice non-capturing.
    label_choice = rf"(?:{alternatives})"
    pattern = re.compile(rf"(?:^|[\s；;，,])(?P<label>{alternatives})\s*[：:][ \t]*(?P<value>.*?)(?=\s*{label_choice}\s*[：:]|[；;\n]|$)")
    next_label = re.compile(rf"^{label_choice}\s*[：:]")
    label_keys = {compact_label(label): key for key, variants in labels.items() for label in variants}
    result: dict[str, list[dict]] = {key: [] for key in labels}
    for text, entry in lines:
        if entry.get("table_cell"):
            following_cell = entry.get("table_following_text")
            if following_cell is not None and compact_label(following_cell.rstrip("：:").strip()) not in label_keys:
                continue
            if compact_label(text.rstrip("：:").strip()) in label_keys:
                text = text.rstrip("：:").strip()
        for match in pattern.finditer(text):
            raw = match.group("value").strip().strip("，,")
            if not unfilled_value(raw):
                continue
            following = entry.get("following_text", "")
            continuation = bool(following) and not next_label.match(following)
            if match.end() < len(text) or entry.get("table_pair"):
                continuation = False
            # A label shown as an example cannot establish an empty form cell.
            illustrative = bool(re.search(r"示例|例如|例子|填写说明|样例|example", text[:match.start()], re.IGNORECASE))
            observation = {"text": text, "label": match.group("label"), "value": raw,
                           "location": entry.get("location", "文本"), "method": entry.get("method", "text"),
                           "confidence": entry.get("confidence"), "reason": "placeholder" if raw else "empty_value",
                           "continuation_possible": bool(continuation or illustrative)}
            observation.update({key: entry[key] for key in ("docx_paragraph", "docx_table_row") if key in entry})
            result[label_keys[compact_label(match.group("label"))]].append(observation)
        bare_label = text.rstrip("：:").strip()
        if compact_label(bare_label) in label_keys and not pattern.search(text):
            result[label_keys[compact_label(bare_label)]].append({"text": text, "label": bare_label, "value": "",
                "location": entry.get("location", "文本"), "method": entry.get("method", "text"),
                "confidence": entry.get("confidence"), "reason": "label_without_value_boundary", "continuation_possible": True})
    return result


def merge_labelled_absence(document: dict, fields: dict, empty: dict, missing_policy: str, labels: dict) -> None:
    """A failed label search proves absence only under an explicit form contract."""
    coverage = field_text_coverage(document)
    document["field_text_coverage"] = coverage
    for key, field in fields.items():
        observations = empty.get(key, [])
        if field.get("unparsed_evidence") and field["values"]:
            field["status"] = "uncertain"
            field["review_reason"] = "同一字段含未能可靠解释的非空值，须核对各处内容"
            field["locations"] = list(dict.fromkeys([*field["locations"],
                *(item["location"] for item in field["unparsed_evidence"])]))
        # The explicit JSON table owns its own omission and conflict semantics.
        if "structured_absence" in field:
            continue
        if observations:
            field["empty_evidence"] = observations
            field["locations"] = list(dict.fromkeys([*(item["location"] for item in observations), *field["locations"]]))
            if field["values"]:
                # Repeated empty and filled labels are not interchangeable.
                field["status"] = "ambiguous"
                field["review_reason"] = "同一字段同时出现空标签和已填写值，须核对各处内容"
        if field["values"]:
            continue
        if not observations and missing_policy != "fail_when_complete":
            continue
        if not observations and not field.get("unparsed_evidence"):
            uncertain_labels = [{"text": entry["text"], "location": entry.get("location", "文本"), "reason": "unparsed_label_boundary"}
                                for entry in document.get("entries", [])
                                if any(re.search(re.escape(label) + r"\s*[：:]", entry.get("text", "")) for label in labels[key])]
            if uncertain_labels:
                field["unparsed_evidence"] = uncertain_labels
                field["locations"] = list(dict.fromkeys(item["location"] for item in uncertain_labels))
        observation = {"reason": "empty_value" if observations else "missing_label", "field": key,
                       "missing_policy": missing_policy, "scope": "document_text",
                       "checked_entry_count": len(document.get("entries", [])), "coverage": coverage,
                       **({"empty_evidence": observations} if observations else {})}
        field["native_observation"] = observation
        if field.get("unparsed_evidence"):
            field["review_reason"] = "原稿含字段标签，但日期、值或分界未能可靠解释，须核对原稿"
        elif any(item["continuation_possible"] for item in observations):
            field["review_reason"] = "字段值可能在后续行或缺少明确分界，须核对原稿"
        elif not coverage["complete"]:
            field["review_reason"] = "原稿含图片、OCR、未读取部件或待核验文字，字段是否缺失须核对原稿"
        else:
            field["absence_confirmed"] = True
            field["native_absence"] = observation
            if not observations:
                field["locations"] = ["原稿全文（必填标签核对）"]
