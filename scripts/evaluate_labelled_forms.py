"""Score an explicit labelled-form contract without changing the fixed corpus."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.application.service import AuditService
from formatly.files import write_json
from formatly.plugins.registry import PluginRegistry
from scripts.evaluate_public_school_corpus import load_manifest, prepare_profiles, SOURCE_CACHE, specimen
from scripts.score_acceptance import score_gold


def evaluate(output: Path, baseline: Path) -> dict:
    """Reuse the original bytes and truth; only the explicit input contract changes."""
    manifest = load_manifest()
    ruleset = next(item for item in manifest["rulesets"] if item["id"] == "ruc-certificate")
    cases = [case for case in manifest["cases"] if case["ruleset"] == ruleset["id"]]
    original = json.loads((baseline / "dataset.json").read_text(encoding="utf-8"))
    original_inputs = {item["case_id"]: item["input_sha256"] for item in original["executions"]}
    output = output.resolve()
    if output.exists():
        raise ValueError("请使用新的输出目录以保留既有验收证据")
    output.mkdir(parents=True)
    (output / "specimens").mkdir()
    gold: dict[str, Any] = {"schema_version": 1, "school": "公开字段要求＋显式标签表单输入契约", "reviewers": ["固定原73样本的独立gold；非学校专家"],
            "locked_at": manifest["locked_at"], "cases": []}
    executions, contract_failures = [], []
    selected = deepcopy(manifest)
    selected["rulesets"] = [ruleset]
    service = AuditService(output / "service", registry=PluginRegistry(discover=False))
    try:
        profiles, _ = prepare_profiles(service, selected, source_cache=SOURCE_CACHE)
        profile = deepcopy(profiles[ruleset["id"]])
        profile["id"] += "-labelled"
        profile["name"] = "必填标签表单局部基准"
        profile["settings"]["fields"]["missing_policy"] = "fail_when_complete"
        profile["description"] = "基准明确约定原稿按字段标签填写；该约定不代表公开来源要求此种表单布局。"
        profile = service.save_profile(profile)
        write_json(output / "profile.json", profile)
        for case in cases:
            data = specimen(case, ruleset)
            digest = hashlib.sha256(data).hexdigest()
            if digest != original_inputs.get(case["id"]):
                raise ValueError("原稿输入与原73基准不一致：" + case["id"])
            filename = case["id"] + "." + case["format"]
            (output / "specimens" / filename).write_bytes(data)
            job = service.create(data, filename, kind=ruleset["kind"], profile_snapshot=profile)
            job = service.run(job["id"])
            if job["status"] != "completed":
                raise RuntimeError("检测未完成：" + case["id"])
            report = service.jobs_dir / job["id"] / "report.json"
            result = json.loads(report.read_text(encoding="utf-8"))
            requirements = []
            for rule in ruleset["requirements"]:
                expected = case["gold"][rule["id"]]
                requirements.append({"requirement_id": rule["id"], "target": rule["target"], "status": expected,
                                     "group": case["format"], "review_note": case["note"]})
                statuses = {check["status"] for check in result["coverage"]["checks"] if check.get("requirement_id") == rule["id"]}
                allowed = {"manual"} if rule["mode"] == "manual" else {"failed" if expected == "fail" else "passed"}
                if not statuses or not statuses <= allowed:
                    contract_failures.append({"case_id": case["id"], "requirement_id": rule["id"], "actual": sorted(statuses), "allowed": sorted(allowed)})
            gold["cases"].append({"case_id": case["id"], "kind": ruleset["kind"], "input_sha256": digest,
                                  "report": report.relative_to(output).as_posix(), "requirements": requirements})
            executions.append({"case_id": case["id"], "format": case["format"], "input_sha256": digest, "job_id": job["id"]})
    finally:
        service.close()
    write_json(output / "gold.json", gold)
    scored = score_gold(gold, output)
    summary = {"schema": "formatly.labelled-form-evaluation.v1", "sample_count": len(cases),
               "formats": dict(Counter(case["format"] for case in cases)), "input_bytes_match_default_cohort": True,
               "original_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
               "policy": "fail_when_complete", "scope": profile["description"], "metrics": scored["metrics"],
               "uncovered_statuses": scored["uncovered_statuses"], "invalid_evidence_count": scored["invalid_evidence_count"],
               "contract_failures": contract_failures, "executions": executions,
               "passed": not contract_failures and not scored["invalid_evidence_count"] and not any(row["outcome"] in {"fp", "fn"} for row in scored["cases"])}
    write_json(output / "metrics.json", scored)
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True, help="Completed default 73-case evaluation directory")
    args = parser.parse_args()
    result = evaluate(args.output, args.baseline)
    print(json.dumps({key: value for key, value in result.items() if key != "executions"}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
