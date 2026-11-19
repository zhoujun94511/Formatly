"""Run trusted built-in requirements with independent, explicit scope settings."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
import json

from ..domain import AuditContext, AuditPlugin, Issue, PluginResult
from ..persistence.school_compiler import expected_key, needs_binding, pdf_region_compatible, remove_target, requirement_scope, rule_settings, scope_unresolved, value_key


@dataclass
class ScopedIssue(Issue):
    requirement_ids: list[str] = field(default_factory=list)


def _run(plugin: AuditPlugin, context: AuditContext, settings: dict, scope: dict | None = None) -> PluginResult:
    cache = dict(context.cache)
    cache.pop("_active_requirement_scope", None)
    if scope is not None:
        cache["_active_requirement_scope"] = scope
    local = replace(context, settings=deepcopy(settings), cache=cache)
    before = json.dumps(local.settings, sort_keys=True, allow_nan=False)
    output = plugin.run(local)
    if json.dumps(local.settings, sort_keys=True, allow_nan=False) != before:
        raise ValueError("范围规则执行期间参数被修改")
    context.cache.update({key: value for key, value in local.cache.items() if key != "_active_requirement_scope"})
    return output


def run_scoped_plugin(plugin: AuditPlugin, context: AuditContext, profile: dict) -> PluginResult:
    rules = [item for item in profile.get("scoped_rules", []) if item["plugin_id"] == plugin.id and item["kind"] == context.kind]
    if not rules:
        return plugin.run(context)
    if plugin.id not in {"generic-format", "academic-format", "academic-structure", "document-fields"}:
        raise ValueError("范围执行仅支持已声明的内置检测器")
    base = deepcopy(context.settings)
    for item in rules:
        remove_target(base, item["target"])
    output = _run(plugin, context, base)
    # Empty configuration notices belong to the individual requirements below.
    output.checks = [check for check in output.checks if check.get("target") not in {"academic.settings", "structure.settings"}]
    groups: dict[str, list[dict]] = {}
    for item in rules:
        signature = value_key({**{key: item.get(key) for key in ("target", "parameters", "scope_style_ids",
                                "scope_section_indices", "scope_binding_status")},
                               "expected": expected_key(item["target"], item.get("expected"))})
        groups.setdefault(signature, []).append(item)
    records = []
    for items in groups.values():
        item = items[0]
        identities = [value["id"] for value in items]
        scope_type, scope = requirement_scope(item)
        disabled = item.get("expected") is False and item["target"].startswith("structure.")
        pdf_body = (context.input_path.suffix.lower() == ".pdf"
                    and (item["target"] in {"body.font", "body.size_pt"} or item["target"].startswith("body.fonts.")))
        unsupported = not pdf_body and context.input_path.suffix.lower() != ".docx" and (needs_binding(item) or item.get("scope_binding_status") == "unbound")
        if disabled or unsupported or scope_unresolved(item) and not pdf_body:
            state = "not_checked" if disabled else "unsupported" if unsupported else "manual"
            reason = ("该结构检查已明确关闭，不作为反向要求或自动通过" if state == "not_checked" else
                      "当前格式不提供DOCX样式或分节范围证据，不能执行该范围要求" if unsupported else "尚未确认实际原稿的检查范围")
            checks = [{"rule_id": item["target"], "target": item["target"], "expected": item.get("expected"),
                       "actual": None, "status": state, "reason": reason, "location": "实际原稿范围", "kind": "format"}]
            issues = []
            evidence = {"executed": False, "reason": reason}
        else:
            settings = rule_settings(item)
            if pdf_body and pdf_region_compatible(item, profile) and context.settings.get("body", {}).get("pdf_region_mm"):
                settings["body"]["pdf_region_mm"] = deepcopy(context.settings["body"]["pdf_region_mm"])
            if item["target"].startswith("page."):
                settings["page"]["tolerance_mm"] = context.settings.get("page", {}).get("tolerance_mm", 1)
            local_output = _run(plugin, context, settings, {"kind": scope_type, "values": scope})
            checks = [check for check in local_output.checks if check.get("target", check.get("rule_id")) == item["target"]]
            if pdf_body and not pdf_region_compatible(item, profile):
                for check in checks:
                    check["reason"] = "PDF未提供逐条对应的正文区域映射；不能用一个区域替代不同的DOCX样式范围"
            issues = [issue for issue in local_output.issues if any(
                issue.rule_id == check.get("rule_id") and issue.location == check.get("location", "文件")
                and issue.expected == check.get("expected") and issue.actual == check.get("actual") for check in checks)]
            evidence = local_output.evidence
            if local_output.status != "completed":
                output.status = "incomplete"
        for check in checks:
            check.update(requirement_id=identities[0], requirement_ids=identities,
                         scope_style_ids=scope if scope_type == "styles" else [],
                         scope_section_indices=scope if scope_type == "sections" else [])
        output.checks.extend(checks)
        output.issues.extend(ScopedIssue(**issue.to_dict(), requirement_ids=identities) for issue in issues)
        records.append({"requirement_ids": identities, "target": item["target"], "evidence": evidence})
    output.evidence = {**output.evidence, "scoped_execution": records}
    return output
