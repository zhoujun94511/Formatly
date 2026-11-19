"""Score Formatly reports against an expert-annotated acceptance gold set.

Only valid automatic ``passed``/``failed`` observations are included in the
classification metrics. Manual, unsupported, not-checked, missing and
invalidated evidence are reported separately. Gold marked ``manual`` has no
independent binary truth yet and remains outside those classification metrics.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any


GOLD_STATUSES = {"pass", "fail", "manual"}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无效：{path}（{exc.msg}）") from exc


def _report_result(value: Any, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"报告必须是 JSON 对象：{path}")
    result = value.get("result", value)
    if not isinstance(result, dict):
        raise ValueError(f"报告缺少 result 对象：{path}")
    coverage = result.get("coverage")
    if not isinstance(coverage, dict) or not isinstance(coverage.get("checks"), list):
        raise ValueError(f"报告缺少 coverage.checks：{path}")
    return result


def _metric(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item["outcome"] for item in items if item["outcome"] in {"tp", "fp", "fn", "tn"})
    tp, fp, fn, tn = (counts[name] for name in ("tp", "fp", "fn", "tn"))
    covered = tp + fp + fn + tn
    total = len(items)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    accuracy = (tp + tn) / covered if covered else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision,
            "recall": recall, "f1": f1, "accuracy": accuracy,
            "covered": covered, "total": total, "coverage": covered / total if total else None}


def _integrity_errors(result: dict[str, Any]) -> list[str]:
    """Keep invalidated evidence outside the classification denominator."""
    errors = [key for key in ("input_unchanged", "pdf_unchanged", "rules_unchanged") if result.get(key) is False]
    for check in result["coverage"]["checks"]:
        if isinstance(check, dict) and check.get("kind") == "integrity" and check.get("status") == "error":
            errors.append(str(check.get("rule_id") or "integrity.error"))
    for issue in result.get("issues", []):
        if isinstance(issue, dict) and issue.get("category") == "integrity" and issue.get("level") == "error":
            errors.append(str(issue.get("rule_id") or "integrity.error"))
    return list(dict.fromkeys(errors))


def _evidence_index(result: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    engines = result.get("engines", [])
    if isinstance(engines, dict):
        engines = [{**value, "id": identity} for identity, value in engines.items() if isinstance(value, dict)]
    engines = [engine for engine in engines if isinstance(engine, dict)]
    by_engine = {engine["id"]: engine for engine in engines if isinstance(engine.get("id"), str)}
    by_check = {check["check_id"]: {**check, "plugin": engine.get("id")}
                for engine in by_engine.values() for check in engine.get("checks", [])
                if isinstance(check, dict) and isinstance(check.get("check_id"), str)}
    return by_engine, by_check


def _observation_errors(result: dict[str, Any], observations: list[dict[str, Any]],
                        by_engine: dict[str, dict[str, Any]], by_check: dict[str, dict[str, Any]]) -> list[str]:
    """An unrelated engine failure must not invalidate completed evidence."""
    errors: list[str] = []
    for observation in observations:
        sources = [observation]
        for identity in observation.get("observed_check_ids", []):
            source = by_check.get(identity)
            if source is None:
                errors.append("missing_observation:" + str(identity))
            else:
                sources.append(source)
        completed_source = False
        for source in sources:
            plugin_id = source.get("plugin")
            engine = by_engine.get(plugin_id) if isinstance(plugin_id, str) else None
            if engine is not None:
                if engine.get("status") != "completed":
                    errors.append("engine_not_completed:" + str(engine.get("id")))
                else:
                    completed_source = True
        if (result.get("status") == "incomplete" or result.get("execution_errors", 0)) and not completed_source:
            errors.append("execution_evidence_unverified")
    return list(dict.fromkeys(errors))


def score_gold(gold: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    if gold.get("schema_version") != 1 or not isinstance(gold.get("cases"), list):
        raise ValueError("gold 文件必须使用 schema_version=1 并包含 cases 数组")
    base_dir = (base_dir or Path.cwd()).resolve()
    entries: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for case in gold["cases"]:
        if not isinstance(case, dict):
            raise ValueError("每个 case 必须是对象")
        case_id, kind = case.get("case_id"), case.get("kind")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id 必须是非空字符串")
        if case_id in seen_cases:
            raise ValueError(f"重复 case_id：{case_id}")
        seen_cases.add(case_id)
        if kind not in {"thesis", "intern", "certificate"}:
            raise ValueError(f"{case_id} 的 kind 无效")
        report_path = Path(str(case.get("report", "")))
        if not report_path.is_absolute():
            report_path = base_dir / report_path
        if not report_path.is_file():
            raise ValueError(f"{case_id} 的报告不存在：{report_path}")
        result = _report_result(_read_json(report_path), report_path)
        if result.get("kind") not in (None, kind):
            raise ValueError(f"{case_id} 的报告 kind 与 gold 不一致：{result.get('kind')} != {kind}")
        expected_hash = case.get("input_sha256")
        if expected_hash and result.get("input_sha256") != expected_hash:
            raise ValueError(f"{case_id} 的报告 input_sha256 与 gold 不一致")
        integrity_errors = _integrity_errors(result)
        engines_by_id, checks_by_id = _evidence_index(result)
        checks = result["coverage"]["checks"]
        by_requirement: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for check in checks:
            if isinstance(check, dict) and check.get("requirement_id"):
                by_requirement[str(check["requirement_id"])].append(check)
        seen_requirements: set[str] = set()
        for requirement in case.get("requirements", []):
            if not isinstance(requirement, dict):
                raise ValueError(f"{case_id} 的 requirement 必须是对象")
            rid, target, expected = requirement.get("requirement_id"), requirement.get("target"), requirement.get("status")
            group = requirement.get("group") or "ungrouped"
            if not isinstance(rid, str) or not rid or not isinstance(target, str) or not target:
                raise ValueError(f"{case_id} 的 requirement_id/target 无效")
            if rid in seen_requirements:
                raise ValueError(f"{case_id} 重复 requirement_id：{rid}")
            seen_requirements.add(rid)
            if not isinstance(expected, str) or expected not in GOLD_STATUSES:
                raise ValueError(f"{case_id}/{rid} 的 gold status 必须是 pass、fail 或 manual")
            all_observations = by_requirement.get(rid, [])
            observations = [item for item in all_observations if item.get("target") in (None, target)]
            statuses = [str(item.get("status")) for item in observations]
            invalid_reasons = list(dict.fromkeys(integrity_errors + _observation_errors(result, observations, engines_by_id, checks_by_id)))
            if invalid_reasons:
                predicted = None
            elif statuses and all(status == "passed" for status in statuses):
                predicted = "pass"
            elif any(status == "failed" for status in statuses):
                predicted = "fail"
            else:
                predicted = None
            outcomes = {("fail", "fail"): "tp", ("pass", "fail"): "fp",
                        ("fail", "pass"): "fn", ("pass", "pass"): "tn"}
            outcome = outcomes.get((expected, predicted)) if predicted is not None else None
            entries.append({"case_id": case_id, "kind": kind, "requirement_id": rid,
                            "target": target, "group": group, "gold": expected, "predicted": predicted,
                            "observed_statuses": statuses,
                            "observed_targets": sorted({str(item.get("target")) for item in all_observations if item.get("target")}),
                            "target_mismatch": any(item.get("target") not in (None, target) for item in all_observations),
                            "invalid_reasons": invalid_reasons,
                            "outcome": outcome or "uncovered"})
    covered = [entry for entry in entries if entry["outcome"] in {"tp", "fp", "fn", "tn"}]
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({entry["kind"] for entry in entries}):
        by_kind[kind] = _metric([entry for entry in entries if entry["kind"] == kind])
    by_target: dict[str, dict[str, Any]] = {}
    for target in sorted({entry["target"] for entry in entries}):
        by_target[target] = _metric([entry for entry in entries if entry["target"] == target])
    by_group: dict[str, dict[str, Any]] = {}
    for group in sorted({entry["group"] for entry in entries}):
        by_group[group] = _metric([entry for entry in entries if entry["group"] == group])
    uncovered_statuses = Counter(
        status
        for entry in entries
        if entry["outcome"] == "uncovered"
        for status in (["invalid_evidence"] if entry["invalid_reasons"] else entry["observed_statuses"] or ["missing"])
    )
    return {"schema_version": 1, "school": gold.get("school"), "reviewers": gold.get("reviewers", []),
            "locked_at": gold.get("locked_at"),
            "metrics": _metric(entries), "by_kind": by_kind, "by_target": by_target, "by_group": by_group,
            "uncovered_statuses": dict(sorted(uncovered_statuses.items())),
            "unresolved_gold_count": sum(entry["gold"] == "manual" for entry in entries),
            "invalid_evidence_count": sum(bool(entry["invalid_reasons"]) for entry in entries),
            "uncovered": [entry for entry in entries if entry["outcome"] == "uncovered"],
            "cases": entries, "reports_count": len(gold["cases"]), "covered_cases": len({entry["case_id"] for entry in covered})}


def main() -> int:
    parser = argparse.ArgumentParser(description="统计 Formatly 专家标注验收指标")
    parser.add_argument("--gold", required=True, type=Path, help="gold 标注 JSON")
    parser.add_argument("--output", type=Path, help="输出 metrics JSON；省略时写到标准输出")
    args = parser.parse_args()
    try:
        result = score_gold(_read_json(args.gold), args.gold.parent)
    except ValueError as exc:
        parser.error(str(exc))
    result["gold_sha256"] = hashlib.sha256(args.gold.read_bytes()).hexdigest()
    result["gold_path"] = str(args.gold.resolve())
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
