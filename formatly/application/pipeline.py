"""One pipeline for CLI, HTTP and Python callers."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import time
import traceback

from ..domain import AuditContext, Issue
from ..files import sha256, write_json
from ..privacy import redact_local_paths
from ..documents import document_format
from ..plugins.registry import PluginRegistry, probe_plugin
from .job_control import JobCancelled, checkpoint
from .scoped_execution import run_scoped_plugin
from ..persistence.school_compiler import expected_key, requirement_scope, scope_unresolved

CHECK_STATES = {"passed", "failed", "manual", "not_checked", "unsupported", "error", "not_applicable"}


def _check(value, plugin_id, index):
    if not isinstance(value, dict) or value.get("status") not in CHECK_STATES or not isinstance(value.get("rule_id"), str):
        raise ValueError("插件检查项缺少有效rule_id/status")
    if value.get("kind", "format") not in {"format", "integrity", "content"}:
        raise ValueError("插件检查项kind无效")
    return {"kind": "format", "target": value["rule_id"], "location": "文件", "source": "规则方案", **value,
            "plugin": plugin_id, "check_id": f"{plugin_id}:{index}"}


def _same_expected(target, first, second):
    if target == "required_heading":
        return "".join(str(first).split()).casefold() == "".join(str(second).split()).casefold()
    return expected_key(target, first) == expected_key(target, second)


def _issue_check_ids(issue, checks):
    """Link a public issue to its exact local observations before aggregation."""
    matches = [check for check in checks
               if check["rule_id"] == issue["rule_id"] and check.get("plugin") == issue.get("plugin")
               and check.get("location", "文件") == issue.get("location", "文件")
               and check.get("status") == ("manual" if issue["level"] == "manual" else "failed")
               and check.get("actual") == issue.get("actual")
               and (not issue.get("requirement_ids") or set(issue["requirement_ids"]).intersection(check.get("requirement_ids", [])))
               and (_same_expected(check.get("target"), check.get("expected"), issue.get("expected"))
                    or (check.get("target", "").startswith("field.") and issue.get("expected") is None))]
    # An external plugin may reuse a display location for different targets.
    # Preserve ambiguity rather than attribute its issue to an unrelated clause.
    targets = {(check.get("target"), json.dumps(check.get("expected"), sort_keys=True, ensure_ascii=False)) for check in matches}
    return [check["check_id"] for check in matches] if len(targets) <= 1 else []


def _current_hash(path):
    try:
        return sha256(path)
    except OSError:
        return None


def _requirements(checks, profile, kind, input_format="docx"):
    """Map school clauses to observed execution, never merely to configuration."""
    mapped, consumed = [], set()
    severity = ("error", "failed", "unsupported", "not_checked", "manual", "passed", "not_applicable")
    for requirement in profile.get("requirements", []):
        if requirement["kind"] != kind:
            continue
        target = requirement["target"]
        scope_type, declared_scope = requirement_scope(requirement)
        body_property = (target.startswith("body.") and target != "body.style_ids") or target.startswith("paragraph.")
        scope = requirement.get("scope_style_ids")
        if body_property and scope is None:
            group = "paragraph" if target.startswith("paragraph.") else "body"
            scope_settings = profile.get("settings", {}).get(group, {})
            scope = scope_settings.get("property_style_ids", {}).get(target.removeprefix(group + "."), scope_settings.get("style_ids"))
        scope_unknown = input_format == "docx" and (scope_unresolved(requirement) or body_property and profile.get("school") is not None and not scope)
        matches = []
        for index, check in enumerate(checks):
            if requirement["id"] in check.get("requirement_ids", []) and check.get("target") == target:
                consumed.add(index)
            if requirement.get("excluded") or scope_unknown:
                continue
            if check.get("target") != target:
                continue
            if check.get("requirement_ids") and requirement["id"] not in check["requirement_ids"]:
                continue
            if any(item.get("id") == requirement["id"] for item in profile.get("scoped_rules", [])) and not check.get("requirement_ids"):
                continue
            if scope and not check.get("requirement_ids") and check.get("status") in {"passed", "failed"} and check.get("style_id") not in scope:
                continue
            if not (target.startswith("field.") and requirement.get("expected") is None) and not _same_expected(target, check.get("expected"), requirement.get("expected")):
                continue
            matches.append(check)
            consumed.add(index)
        if not requirement.get("confirmed"):
            status, reason = "not_checked", "学校要求尚未确认，未据此执行检测"
        elif requirement.get("excluded"):
            status, reason = "not_applicable", "已确认排除：" + requirement.get("exclusion_reason", "")
        elif requirement["mode"] == "manual":
            status, reason = "manual", "该条款需人工核对，不计为自动通过"
        elif requirement.get("expected") is False and target.startswith("structure."):
            status, reason = "not_checked", "该结构检查已明确关闭，不计为自动通过"
        elif scope_unknown:
            status, reason = "manual", ("正文适用样式尚未确认，不能用默认样式代替正文要求" if body_property else
                                       "实际原稿检查范围尚未确认，不能用来源模板范围代替")
        elif not matches:
            status, reason = "not_checked", "未取得该要求的执行证据，不能计为通过"
        else:
            status = next(state for state in severity if any(item["status"] == state for item in matches))
            reason = "按已确认学校要求汇总实际检查"
        mapped.append({"rule_id": requirement["id"], "requirement_id": requirement["id"], "target": target,
                       "kind": "content" if target.startswith("field.") else "format", "status": status,
                       "label": requirement.get("label", target), "expected": requirement.get("expected"),
                       "excluded": bool(requirement.get("excluded")), "exclusion_reason": requirement.get("exclusion_reason", ""),
                       "observed_rule_ids": list(dict.fromkeys(item["rule_id"] for item in matches)),
                       "observed_check_ids": [item["check_id"] for item in matches],
                       "scope_style_ids": scope if body_property else declared_scope if scope_type == "styles" else None,
                       "scope_section_indices": declared_scope if scope_type == "sections" else None,
                       "parameters": requirement.get("parameters", {}),
                       **{key: requirement[key] for key in ("scope_binding_status", "source_scope_style_ids", "source_scope_section_indices", "source_parameters") if key in requirement},
                       "actual": [{"location": item.get("location"), "actual": item.get("actual"), "status": item["status"]} for item in matches],
                       "location": requirement.get("source_locator", "学校要求"), "reason": reason,
                       "source": {"source_id": requirement.get("source_id"), "locator": requirement.get("source_locator"),
                                  "excerpt": requirement.get("source_excerpt"), "school": profile.get("school")}})
    return mapped + [check for index, check in enumerate(checks) if index not in consumed]


def execute(context: AuditContext, profile: dict, registry: PluginRegistry) -> dict:
    input_format = document_format(context.input_path)
    profile = json.loads(json.dumps(profile, ensure_ascii=False, allow_nan=False))
    snapshot = json.loads(json.dumps(profile, ensure_ascii=False, allow_nan=False))
    context.settings = json.loads(json.dumps(profile.get("settings", {}), ensure_ascii=False, allow_nan=False))
    before = sha256(context.input_path)
    pdf_before = sha256(context.pdf_path) if context.pdf_path else None
    issues, engines, checks = [], [], []
    incomplete = False
    context.output_dir.mkdir(parents=True, exist_ok=True)
    warnings = registry.validate_settings(profile) if hasattr(registry, "validate_settings") else []
    for warning in warnings:
        issues.append(Issue("configuration.unverified", "manual", warning, category="configuration").to_dict())
        checks.append({"rule_id": "configuration.unverified", "target": "settings", "status": "not_checked", "kind": "content", "reason": warning})
    for plugin_id in profile["plugins"]:
        checkpoint(context, "reading" if plugin_id == "docx-package" else "checking", plugin_id)
        started = time.monotonic()
        record = {"id": plugin_id, "status": "running"}
        try:
            plugin = registry.get(plugin_id)
            if context.kind not in getattr(plugin, "kinds", ("thesis", "intern", "certificate")):
                raise ValueError("插件不支持当前文档类型")
            if input_format not in getattr(plugin, "formats", ("docx",)):
                raise ValueError("插件不支持当前输入格式：" + input_format)
            available, reason = probe_plugin(plugin, input_format)
            if not available:
                raise RuntimeError(reason)
            output = run_scoped_plugin(plugin, context, profile)
            if output.status not in {"completed", "incomplete"}:
                raise ValueError(f"插件返回无效状态: {output.status}")
            plugin_checks = [_check(item, plugin_id, index) for index, item in enumerate(getattr(output, "checks", []))]
            plugin_issues = [{**issue.to_dict(), "plugin": plugin_id} for issue in output.issues]
            for issue in plugin_issues:
                issue["check_ids"] = _issue_check_ids(issue, plugin_checks)
            record.update(status=output.status, evidence=output.evidence, checks=plugin_checks)
            if any(check["status"] == "error" for check in plugin_checks):
                record["status"] = "incomplete"
                incomplete = True
            checks.extend(plugin_checks)
            issues.extend(plugin_issues)
            if not plugin_checks and plugin_id not in {"docx-package", "document-fields"}:
                checks.append({"rule_id": plugin_id + ".coverage", "target": plugin_id, "status": "not_checked",
                               "kind": "format", "plugin": plugin_id, "reason": "插件未提供逐规则执行证据，覆盖须人工复核"})
            if output.status == "incomplete":
                incomplete = True
                issues.append(Issue(plugin_id + ".incomplete", "manual", "引擎报告检测未完成", plugin=plugin_id, category="engine").to_dict())
        except JobCancelled:
            raise
        except Exception as exc:
            incomplete = True
            message = redact_local_paths(str(exc), context.input_path, context.pdf_path, context.output_dir)
            error_type = type(exc).__name__
            record.update(status="failed", error=message, error_type=error_type)
            write_json(context.output_dir / f"engine-{plugin_id.replace('/', '_')}.error.json",
                       {"error": message, "error_type": error_type,
                        "traceback": redact_local_paths(traceback.format_exc(), context.input_path, context.pdf_path, context.output_dir)})
            checks.append({"rule_id": plugin_id + ".engine", "target": plugin_id, "kind": "integrity", "status": "error", "plugin": plugin_id, "reason": message})
            issues.append(Issue(plugin_id + ".engine", "error", "检测引擎未完成，不能视为通过", actual=message, plugin=plugin_id, category="engine").to_dict())
        record["duration_ms"] = round((time.monotonic() - started) * 1000)
        engines.append(record)
        checkpoint(context, "checking", plugin_id)
        if plugin_id == "docx-package" and record["status"] != "completed":
            break  # Never hand malformed input to native/third-party engines.
    checkpoint(context, "verifying", "检查输入与规则完整性")
    unchanged = _current_hash(context.input_path) == before
    pdf_unchanged = _current_hash(context.pdf_path) == pdf_before if context.pdf_path else None
    try:
        rules_unchanged = json.dumps(context.settings, sort_keys=True, allow_nan=False) == json.dumps(profile.get("settings", {}), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        rules_unchanged = False
    for label, valid in (("input", unchanged), ("pdf", pdf_unchanged), ("rules", rules_unchanged)):
        if valid is False:
            incomplete = True
            message = "检测期间规则参数被修改，结果无效" if label == "rules" else "检测输入快照发生变化或不可读，结果无效"
            issues.append(Issue("integrity." + label + "_changed", "error", message, category="integrity").to_dict())
            checks.append({"rule_id": "integrity." + label + "_changed", "target": "integrity." + label, "kind": "integrity", "status": "error", "reason": "检测前后哈希不一致"})
    format_checks = sum(item.get("kind") == "format" and item["status"] in {"passed", "failed", "manual"}
                        and item.get("target") not in {"layout.visual", "legacy.rules"} for item in checks)
    if not format_checks:
        issues.append(Issue("coverage.no_format_rules", "manual", "本次没有取得格式属性规则的执行证据，包有效不代表格式通过").to_dict())
        checks.append({"rule_id": "coverage.no_format_rules", "target": "format.coverage", "status": "not_checked", "kind": "format", "reason": "未执行格式属性规则或插件未声明覆盖证据"})
    for index, check in enumerate(checks):
        check.setdefault("check_id", f"core:{index}")
    coverage_checks = _requirements(checks, profile, context.kind, input_format)
    existing = {(issue["rule_id"], issue.get("location", "文件")) for issue in issues}
    for check in coverage_checks:
        key = (check["rule_id"], check.get("location", "文件"))
        if check["status"] == "error":
            incomplete = True
            if key not in existing:
                issues.append(Issue(check["rule_id"], "error", check.get("reason", "规则执行失败"), check.get("location", "文件"), category="engine").to_dict())
                existing.add(key)
        if check.get("requirement_id") and check["status"] in {"failed", "manual"} and check.get("observed_check_ids"):
            observed = set(check["observed_check_ids"])
            matched_issues = [issue for issue in issues if observed.intersection(issue.get("check_ids", []))]
            for issue in matched_issues:
                sources = issue.setdefault("school_sources", [])
                if check["source"] not in sources:
                    sources.append(check["source"])
                issue["source"] = sources[0] if len(sources) == 1 else list(sources)
                requirement_ids = issue.setdefault("requirement_ids", [])
                if check["requirement_id"] not in requirement_ids:
                    requirement_ids.append(check["requirement_id"])
            if matched_issues:
                continue
        if check["status"] not in {"passed", "error", "not_applicable"} and key not in existing:
            level = "error" if check["status"] == "failed" else "manual"
            issues.append(Issue(check["rule_id"], level, check.get("label") or check.get("reason") or "规则需核对",
                                check.get("location", "文件"), check.get("expected"), check.get("actual"),
                                check.get("source", "规则方案"), check.get("plugin", ""), "format").to_dict())
            existing.add(key)
    summary = {state: sum(item["status"] == state for item in coverage_checks) for state in sorted(CHECK_STATES)}
    counts = dict(Counter(issue["level"] for issue in issues))
    document_counts = dict(Counter(issue["level"] for issue in issues if issue.get("category") not in {"engine", "integrity"}))
    for level in ("error", "warning", "manual"):
        counts.setdefault(level, 0)
        document_counts.setdefault(level, 0)
    execution_errors = sum(issue.get("category") in {"engine", "integrity"} and issue["level"] == "error" for issue in issues)
    unresolved = any(summary[state] for state in ("manual", "not_checked", "unsupported", "error"))
    status = "incomplete" if incomplete else "needs_changes" if counts["error"] else "review_required" if counts["manual"] or counts["warning"] or unresolved else "passed"
    digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    from ..plugins.portable import extraction_summary
    extraction = context.cache.get("document")
    result = {"schema_version": 3, "profile_id": profile["id"], "profile_snapshot": snapshot, "profile_sha256": digest, "kind": context.kind,
              "input_format": input_format, "document_extraction": extraction_summary(extraction) if extraction else None,
              "created_at": datetime.now(timezone.utc).isoformat(), "status": status, "counts": counts,
              "input_sha256": before, "input_unchanged": unchanged, "manual_items_count_as_pass": False,
              "pdf_sha256": pdf_before, "pdf_unchanged": pdf_unchanged,
              "rules_unchanged": rules_unchanged,
              "document_counts": document_counts, "execution_errors": execution_errors,
              "issues": issues, "engines": engines,
              "coverage": {"checks": coverage_checks, "summary": summary, "format_checks": format_checks,
                           "complete": bool(format_checks) and not unresolved and not incomplete,
                           "scope": "school_requirements" if profile.get("school") is not None else "configured_attributes"}}
    write_json(context.output_dir / "report.json", result)
    return result

