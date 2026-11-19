"""Run every fixed compatibility case through the shared application service."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.application.service import AuditService
from formatly.files import sha256, write_json
from formatly.plugins.registry import PluginRegistry
from scripts.compatibility_fixtures import case_input, case_profile

MANIFEST = ROOT / "tests/fixtures/compatibility_dataset.json"


def verify_case(service: AuditService, case: dict, samples: Path) -> dict[str, Any]:
    filename, kind, payload = case_input(case)
    digest = hashlib.sha256(payload).hexdigest()
    samples.mkdir(parents=True, exist_ok=True)
    (samples / filename).write_bytes(payload)
    record: dict[str, Any] = {"id": case["id"], "format": case["format"], "kind": kind, "risks": case["risks"],
                              "input_sha256": digest, "executed": False, "passed": False, "errors": [],
                              "expected_admission": case.get("expected_admission", "accepted"),
                              "expected_job_status": case.get("expected_job_status"),
                              "expected_result_status": case.get("expected_result_status")}
    errors = record["errors"]

    def expect(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        job = service.create(payload, filename, kind=kind, profile_snapshot=case_profile(case))
    except ValueError as exc:
        record.update(executed=True, admission="rejected", error=str(exc))
        expect(case.get("expected_admission", "accepted") == "rejected", "unexpected admission rejection")
        if case.get("error_contains"):
            expect(case["error_contains"] in str(exc), "admission error does not explain the expected boundary")
        record["passed"] = not errors
        return record
    record.update(executed=True, admission="accepted", job_id=job["id"])
    expect(case.get("expected_admission", "accepted") == "accepted", "invalid input was accepted")
    finished = service.run(job["id"])
    result = finished.get("result") or {}
    record.update(job_status=finished["status"], result_status=result.get("status", "incomplete"))
    expect(finished["status"] == case.get("expected_job_status"), "job status differs from fixed gold")
    expect(record["result_status"] == case.get("expected_result_status"), "result status differs from fixed gold")
    directory = service.jobs_dir / job["id"]
    original = directory / ("input." + case["format"])
    expect(original.is_file() and original.read_bytes() == payload and sha256(original) == digest, "original input bytes changed")
    if finished["status"] != "completed":
        record["error"] = finished.get("error") or [engine.get("error") for engine in result.get("engines", []) if engine.get("error")]
        record["report_sha256"] = {name: sha256(directory / name) for name in ("report.json", "report.html", "report.md")
                                   if (directory / name).is_file()}
        expect(record["result_status"] == "incomplete", "failed input acquired a formatting verdict")
        if case.get("error_contains"):
            expect(case["error_contains"] in str(finished.get("error", "")) + json.dumps(result, ensure_ascii=False), "failure did not retain the expected reason")
        record["passed"] = not errors
        return record
    expect(result.get("input_sha256") == digest and result.get("input_unchanged") is True, "report does not bind the unchanged input")
    expect(result.get("manual_items_count_as_pass") is False, "manual items were promoted to passes")
    checks = result["coverage"]["checks"]
    record["check_states"] = {target: sorted({item["status"] for item in checks if item.get("target") == target})
                              for target in sorted({item["target"] for item in checks})}
    gold = {target: [status] for target, status in case.get("expected_checks", {}).items()}
    gold.update(case.get("expected_check_states", {}))
    for target, states in gold.items():
        expect(record["check_states"].get(target) == sorted(states), "check states differ: " + target)
    fields = next((engine["evidence"]["fields"] for engine in result["engines"] if engine["id"] == "document-fields"), {})
    for field, value in case.get("expected_fields", {}).items():
        expect(fields.get(field, {}).get("value") == value, "field value differs: " + field)
    for field, state in case.get("expected_field_statuses", {}).items():
        expect(fields.get(field, {}).get("status") == state, "field resolution differs: " + field)
    extraction = json.loads((directory / "document-extraction.json").read_text(encoding="utf-8"))
    for key, value in case.get("expected_extraction", {}).items():
        expect(extraction.get(key) == value, "extraction differs: " + key)
    for expected in case.get("expected_entries", []):
        expect(any(all(entry.get(key) == value for key, value in expected.items()) for entry in extraction["entries"]), "missing original extraction entry")
    for text in case.get("absent_text", []):
        expect(text not in extraction["text"], "hidden or structural text became original visible content")
    artifacts = {}
    for name in ("report.json", "report.html", "report.md", "document-extraction.json"):
        path = directory / name
        expect(path.is_file() and path.stat().st_size > 0, "missing report artifact: " + name)
        if path.is_file():
            artifacts[name] = sha256(path)
    expect(json.loads((directory / "report.json").read_text(encoding="utf-8")) == result, "stored report differs from service result")
    evidence_ids = []
    for index, _issue in enumerate(result.get("issues", [])[:2]):
        evidence = service.issue_evidence(job["id"], index)
        expect(evidence["job_id"] == job["id"] and evidence["issue_index"] == index
               and evidence["input_sha256"] == digest and evidence["profile_sha256"] == result["profile_sha256"], "issue evidence lost its snapshot identity")
        evidence_ids.append(evidence["issue_key"])
    record.update(report_sha256=artifacts, evidence_keys=evidence_ids, profile_sha256=result["profile_sha256"])
    record["passed"] = not errors
    return record


def run(output: Path, manifest_path: Path = MANIFEST) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValueError("兼容性输出目录必须为空或尚不存在")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    cases = manifest["cases"]
    if (manifest.get("schema_version") != 2 or not cases or len({case["id"] for case in cases}) != len(cases)
            or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", str(case.get("id", "")))
                   or case.get("format") not in {"docx", "pdf", "txt", "md", "json"}
                   or case.get("kind") not in {"thesis", "intern", "certificate"} for case in cases)):
        raise ValueError("兼容性清单版本或样例标识无效")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    service = AuditService(output / "service", PluginRegistry(discover=False))
    try:
        for case in cases:
            try:
                record = verify_case(service, case, output / "samples")
            except (ValueError, RuntimeError, OSError, LookupError, TypeError) as exc:
                record = {"id": case["id"], "format": case["format"], "kind": case["kind"], "risks": case["risks"],
                          "executed": False, "passed": False, "errors": [type(exc).__name__ + ": " + str(exc)]}
            records.append(record)
            write_json(output / "results" / (case["id"] + ".json"), record)
    finally:
        service.close()
    summary = {"schema": "formatly.compatibility-results.v2", "dataset_id": manifest["dataset_id"],
               "created_at": datetime.now(timezone.utc).isoformat(), "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
               "case_count": len(cases), "executed": sum(item["executed"] for item in records),
               "failed": sum(not item["passed"] for item in records), "passed": all(item["passed"] for item in records),
               "formats": dict(Counter(case["format"] for case in cases)), "kinds": dict(Counter(case["kind"] for case in cases)),
               "risks": dict(Counter(risk for case in cases for risk in case["risks"])), "cases": records}
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="运行五格式匿名兼容性风险集并保留逐例结果")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run(args.output.resolve())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({key: value for key, value in summary.items() if key != "cases"}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
