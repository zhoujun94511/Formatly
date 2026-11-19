"""Conservative comparisons backed by matching rules and observed text anchors."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
import hashlib
from pathlib import Path

from .evidence import canonical, observed_checks, resolve_node, validate_snapshot
from ..files import W, read_docx
from ..privacy import redact_local_paths


CheckAnchor = Callable[[dict], list[object] | None]


def _anchors(job: dict, directory: Path | None) -> CheckAnchor:
    result = job["result"]
    if result.get("input_format", "docx") != "docx" or directory is None:
        return lambda check: None
    package = read_docx(directory / "input.docx")
    document = package["document"]
    from ..documents.docx_semantics import read_docx_content
    content = read_docx_content(document, package["styles"], numbering=package.get("numbering"),
                                styles_reason=package.get("styles_reason", ""))
    visible = {p.element: p.text for p in content.paragraphs}
    frequency = Counter(visible.values())
    parents = {child: parent for parent in document.iter() for child in parent}
    text_digest = hashlib.sha256(canonical(list(visible.values())).encode()).hexdigest()
    sections = list(document.iter(W + "sectPr"))

    def anchor(check: dict) -> list[object] | None:
        node = resolve_node(document, check.get("locator") or {}, result["input_sha256"])
        if node is None:
            return None
        paragraph = node
        while paragraph is not None and paragraph.tag != W + "p":
            paragraph = parents.get(paragraph)
        if paragraph in visible:
            text = visible[paragraph]
            if not text or frequency[text] != 1:
                return None
            if node is paragraph:
                return ["paragraph", text]
            runs = list(paragraph.iter(W + "r"))
            if node not in runs:
                return None
            run_text = "".join(t.text or "" for t in node.iter(W + "t"))
            if not run_text or sum("".join(t.text or "" for t in r.iter(W + "t")) == run_text for r in runs) != 1:
                return None
            return ["run", text, run_text]
        if node.tag == W + "sectPr":
            # A section number alone is unsafe after text/section reordering.
            return ["section", text_digest, len(sections), sections.index(node)]
        return None

    return anchor


def compare_jobs(source: dict, current: dict, source_directory: Path | None = None,
                 current_directory: Path | None = None) -> dict:
    response: dict = {"source_job_id": source.get("id"), "job_id": current.get("id"), "available": False,
                "reason": "", "groups": {name: [] for name in ("resolved", "remaining", "new", "incomparable")},
                "summary": {name: 0 for name in ("resolved", "remaining", "new", "incomparable")},
                "scope": "observed_checks"}
    try:
        before = validate_snapshot(source, source_directory)
        after = validate_snapshot(current, current_directory)
        if before.get("kind") != after.get("kind") or before.get("input_format") != after.get("input_format"):
            raise ValueError("材料类型或原稿格式发生变化，不能直接比较")
        if before.get("profile_sha256") != after.get("profile_sha256"):
            raise ValueError("规则方案已变化，不能把规则变化计为问题已解决")
        if (before.get("document_extraction") or {}).get("complete") is False or (after.get("document_extraction") or {}).get("complete") is False:
            raise ValueError("原稿未完整读取，不能确定问题变化")
        old_anchor, new_anchor = _anchors(source, source_directory), _anchors(current, current_directory)
    except (ValueError, OSError) as exc:
        response["reason"] = redact_local_paths(str(exc))
        return response

    def signature(recorded_check: dict, lookup_anchor: CheckAnchor) -> str | None:
        target = recorded_check.get("target", recorded_check.get("rule_id"))
        position = lookup_anchor(recorded_check)
        if position is None and target in {"required_heading", "references.citation_order", "references.citation_unique"}:
            position = ["whole_document_rule", target]
        if position is None:
            return None
        return canonical([recorded_check.get("plugin"), recorded_check.get("rule_id"), target,
                          recorded_check.get("expected"), recorded_check.get("style_id"), position])

    old_checks, new_checks = observed_checks(before), observed_checks(after)
    buckets: list[dict[str | None, list[dict]]] = []
    for checks, anchor_function in ((old_checks, old_anchor), (new_checks, new_anchor)):
        grouped: dict[str | None, list[dict]] = defaultdict(list)
        for candidate in checks:
            if candidate.get("kind") == "integrity":
                continue
            key = signature(candidate, anchor_function)
            grouped[key].append(candidate)
        buckets.append(grouped)
    old_grouped, new_grouped = buckets

    def entry(before_check: dict | None, after_check: dict | None, reason: str = "") -> dict:
        displayed_check = after_check if after_check is not None else before_check
        if displayed_check is None:
            raise ValueError("缺少可比较的检查记录")
        return {"rule_id": displayed_check.get("rule_id"), "target": displayed_check.get("target"),
                "location": displayed_check.get("location", "文件"), "expected": displayed_check.get("expected"),
                "before": before_check.get("actual") if before_check else None,
                "after": after_check.get("actual") if after_check else None,
                "before_status": before_check.get("status") if before_check else None,
                "after_status": after_check.get("status") if after_check else None,
                "reason": reason}

    for key in set(old_grouped) | set(new_grouped):
        olds, news = old_grouped.get(key, []), new_grouped.get(key, [])
        if key is None or len(olds) != 1 or len(news) != 1:
            response["groups"]["incomparable"].extend(entry(item, None, "缺少唯一、稳定的对应位置或另一版本没有执行此项") for item in olds if item.get("status") == "failed")
            response["groups"]["incomparable"].extend(entry(None, item, "缺少唯一、稳定的对应位置或另一版本没有执行此项") for item in news if item.get("status") == "failed")
            continue
        old, new = olds[0], news[0]
        before_status, after_status = old.get("status"), new.get("status")
        pair = (before_status, after_status)
        group = None
        if isinstance(before_status, str) and isinstance(after_status, str):
            group = {("failed", "passed"): "resolved", ("failed", "failed"): "remaining", ("passed", "failed"): "new"}.get((before_status, after_status))
        if group:
            response["groups"][group].append(entry(old, new))
        elif "failed" in pair:
            response["groups"]["incomparable"].append(entry(old, new, "一侧缺少确定的自动检查结论"))
    for group in response["groups"].values():
        group.sort(key=lambda item: canonical([item["rule_id"], item["location"], item["expected"]]))
    try:
        # Anchor parsing and matching may take time; publish only while both
        # inputs still match the snapshots used by the recorded checks.
        validate_snapshot(source, source_directory)
        validate_snapshot(current, current_directory)
    except (ValueError, OSError) as exc:
        response["groups"] = {name: [] for name in response["groups"]}
        response["reason"] = redact_local_paths(str(exc))
        return response
    response["available"] = True
    response["summary"] = {name: len(items) for name, items in response["groups"].items()}
    response["reason"] = "仅比较规则和文字位置可可靠匹配的自动检查；人工项及无对应证据不计为已解决。"
    return response
