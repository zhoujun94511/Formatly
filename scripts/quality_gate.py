"""Run fixed document cohorts and reject evidence or version regressions."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_public_school_corpus import evaluate, load_manifest, with_additional_cases

BASELINE = ROOT / "tests/fixtures/quality_baseline.json"


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def mutation_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Freeze independent format deviations before running any detector.

    These anonymous additive cases do not replace the published fixed cohort.
    They test generalisation to different values and combined deviations; they
    are not expert-labelled real submissions or a permanently unseen gold set.
    """
    result = deepcopy(manifest)
    cases = []
    variations = [
        ("geometry", {"overrides": {"page.width_mm": 216, "page.margins.right": 37}},
         {"page.width_mm", "page.margins_mm.right"}),
        ("typography", {"overrides": {"body.size_pt": 14.5, "body.line_spacing": 1.75}},
         {"body.size_pt", "body.line_spacing"}),
        ("font-override", {"direct_font": "黑体"}, {"body.fonts.eastAsia"}),
        ("later-section", {"second_section": {"left": 41}}, {"page.margins_mm.left"}),
        ("combined", {"overrides": {"page.height_mm": 310, "body.size_pt": 15}, "direct_font": "黑体"},
         {"page.height_mm", "body.size_pt", "body.fonts.eastAsia"}),
    ]
    for ruleset in manifest["rulesets"]:
        if ruleset["kind"] == "certificate":
            continue
        for name, changes, failed in variations:
            cases.append({"id": "holdout-" + ruleset["id"] + "-" + name, "ruleset": ruleset["id"],
                          "format": "docx", **deepcopy(changes),
                          "gold": {rule["id"]: "fail" if rule["target"] in failed else "pass"
                                   for rule in ruleset["requirements"]},
                          "note": "独立数值及组合变异；预期在检测前依据显式OOXML属性锁定。"})
    result["cases"] = cases
    result["scope"] = "匿名DOCX独立数值与组合变异队列；非真实学校专家盲测。"
    return result


def cohort_snapshot(output: Path, summary: dict[str, Any], elapsed: float) -> dict[str, Any]:
    scores = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    gold = json.loads((output / "gold.json").read_text(encoding="utf-8"))
    locked_cases = [{"case_id": case["case_id"], "input_sha256": case["input_sha256"],
                     "requirements": case["requirements"]} for case in gold["cases"]]
    sources = summary["source_extraction"]
    return {"dataset_sha256": fingerprint(locked_cases), "sample_count": summary["sample_count"],
            "metrics": scores["metrics"], "by_format": scores["by_group"], "by_target": scores["by_target"],
            "invalid_evidence_count": scores["invalid_evidence_count"],
            "detection_contracts_passed": summary["detection_contracts_passed"],
            "sources": {source["source_id"]: {"sha256": source.get("original_sha256"),
                "measured": source["original_available"], "hits": source["scoped_hits"],
                "total": source["scoped_gold_count"]} for source in sources},
            "performance": {"elapsed_seconds": round(elapsed, 6)}}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(label + " must be a finite non-negative number")
    return float(value)


def compare(current: dict[str, Any], baseline: dict[str, Any] | None, *,
            max_coverage_drop: float = 0, max_slowdown: float | None = None) -> list[str]:
    """Compare immutable cohort identities and every measured group.

    Missing groups and unavailable evidence are failures, never zero-filled
    successes. Optional timing comparisons require an explicit compatible run.
    """
    drop = _number(max_coverage_drop, "max_coverage_drop")
    if drop > 1:
        raise ValueError("max_coverage_drop must be at most 1")
    if max_slowdown is not None:
        _number(max_slowdown, "max_slowdown")
        if baseline is None or current.get("environment") != baseline.get("environment"):
            raise ValueError("Timing comparison needs a baseline from the same controlled environment")
    failures = []
    if baseline is not None and set(baseline["cohorts"]) != set(current["cohorts"]):
        failures.append("cohort set changed")
    for name, cohort in current["cohorts"].items():
        prefix = name + ": "
        previous = baseline["cohorts"].get(name) if baseline is not None else None
        if previous is not None and (cohort["dataset_sha256"] != previous["dataset_sha256"]
                                     or cohort["sample_count"] != previous["sample_count"]):
            failures.append(prefix + "dataset identity changed; establish a separately reviewed baseline")
        if not cohort["detection_contracts_passed"] or cohort["invalid_evidence_count"]:
            failures.append(prefix + "invalid evidence or capability contract")
        for source_id, source in cohort["sources"].items():
            if not source["measured"] or source["hits"] != source["total"]:
                failures.append(prefix + "source extraction incomplete: " + source_id)
        if previous is not None and cohort["sources"] != previous["sources"]:
            failures.append(prefix + "source identity or scoped extraction changed")
        for group_key in ("metrics", "by_format", "by_target"):
            groups = {"all": cohort["metrics"]} if group_key == "metrics" else cohort[group_key]
            old_groups = ({"all": previous["metrics"]} if group_key == "metrics" else previous[group_key]) if previous is not None else {}
            if previous is not None and set(groups) != set(old_groups):
                failures.append(prefix + group_key + " groups changed")
            for group, metric in groups.items():
                tag = prefix + group_key + "/" + group
                if metric["fp"] or metric["fn"]:
                    failures.append(tag + ": false positive/negative")
                old = old_groups.get(group)
                if old is not None:
                    if metric["total"] != old["total"]:
                        failures.append(tag + ": denominator changed")
                    now_coverage, old_coverage = metric.get("coverage"), old.get("coverage")
                    if now_coverage is None or old_coverage is None or _number(now_coverage, tag) + drop < _number(old_coverage, tag):
                        failures.append(tag + ": coverage regressed or unavailable")
        if max_slowdown is not None and previous is not None:
            observed = _number(cohort.get("performance", {}).get("elapsed_seconds"), prefix + "elapsed")
            prior = _number(previous.get("performance", {}).get("elapsed_seconds"), prefix + "baseline elapsed")
            if prior <= 0:
                raise ValueError("Timing baseline must be positive")
            if observed > prior * (1 + max_slowdown):
                failures.append(prefix + "elapsed time regressed")
    return failures


def run(output: Path, source_cache: Path, *, download_sources: bool = False) -> dict[str, Any]:
    from scripts.evaluate_public_school_corpus import download_sources as fetch_sources
    if output.exists() and any(output.iterdir()):
        raise ValueError("Quality output must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    fixed = with_additional_cases(load_manifest(), ROOT / "tests/fixtures/structured_field_cases.json")
    if download_sources:
        fetch_sources(fixed, source_cache)
    value: dict[str, Any] = {"schema": "formatly.quality.v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"os": platform.system(), "arch": platform.machine(), "python": platform.python_version()},
        "scope": "Fixed public clauses and anonymous mutations; not expert-labelled real submissions", "cohorts": {}}
    for name, manifest in (("fixed", fixed), ("mutation", mutation_manifest(fixed))):
        started = time.perf_counter()
        destination = output / name
        summary = evaluate(destination, manifest=manifest, source_cache=source_cache, include_supplemental=False)
        value["cohorts"][name] = cohort_snapshot(destination, summary, time.perf_counter() - started)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="运行完整匿名业务基准与版本退化门禁")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-cache", type=Path, default=ROOT / ".formatly/acceptance/public-school-sources")
    parser.add_argument("--download-sources", action="store_true")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--record-baseline", action="store_true", help="仅建立独立待审基线，不覆盖已有文件")
    parser.add_argument("--max-coverage-drop", type=float, default=0)
    parser.add_argument("--max-slowdown", type=float, help="仅在同一受控环境中比较耗时，例0.2表示最多慢20%%")
    args = parser.parse_args()
    if args.record_baseline and args.baseline.exists():
        parser.error("Baseline exists; choose a new path for explicit review")
    try:
        baseline = None if args.record_baseline else json.loads(args.baseline.read_text(encoding="utf-8"))
        value = run(args.output.resolve(), args.source_cache.resolve(), download_sources=args.download_sources)
        failures = compare(value, baseline, max_coverage_drop=args.max_coverage_drop, max_slowdown=args.max_slowdown)
        value["passed"], value["failures"] = not failures, failures
        (args.output / "quality.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.record_baseline and not failures:
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            with args.baseline.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps({"passed": not failures, "failures": failures,
                      "cohorts": {name: item["sample_count"] for name, item in value["cohorts"].items()}}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
