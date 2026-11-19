"""Evaluate fixed anonymous structure cases through the shared service."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import tracemalloc
from typing import Any
import uuid
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.application.service import AuditService
from formatly.files import NS, sha256, write_json
from formatly.plugins.registry import PluginRegistry

MANIFEST = ROOT / "tests/fixtures/academic_structure_cases.json"
_SECTION = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/></w:sectPr>'


def sample_bytes(case: dict, styles: str) -> bytes:
    """Package the fixture's source XML independently of detection code."""
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="doc" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "word/document.xml": '<w:document xmlns:w="' + NS["w"] + '"><w:body>' + case["body_xml"].replace("{section}", _SECTION) + '</w:body></w:document>',
        "word/styles.xml": '<w:styles xmlns:w="' + NS["w"] + '">' + styles + '</w:styles>',
        **case.get("parts", {}),
    }
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, xml in parts.items():
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, xml.encode("utf-8"))
    return stream.getvalue()


def evaluate(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    run_dir = output / ("run-" + uuid.uuid4().hex)
    samples = run_dir / "samples"
    samples.mkdir(parents=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    by_target: dict[str, Counter] = {}
    expected_counts: Counter[str] = Counter()
    observed_counts: Counter[str] = Counter()
    started = time.perf_counter()
    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    try:
        with closing(AuditService(run_dir / "data", PluginRegistry(discover=False))) as service:
            for case in manifest["cases"]:
                payload = sample_bytes(case, manifest["styles_xml"])
                source = samples / (case["id"] + ".docx")
                source.write_bytes(payload)
                profile = service.save_profile({"id": "structure-" + case["id"][:49], "name": "匿名结构基准",
                                                "plugins": ["docx-package", "academic-structure"],
                                                "settings": {"structure": case["structure"]}})
                item: dict[str, Any] = {"id": case["id"], "format": "docx", "purpose": case["purpose"],
                                        "input_sha256": hashlib.sha256(payload).hexdigest(),
                                        "gold_sha256": hashlib.sha256(json.dumps(case["gold"], sort_keys=True).encode()).hexdigest(),
                                        "profile_sha256": hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True,
                                                                                    separators=(",", ":")).encode("utf-8")).hexdigest(),
                                        "gold": case["gold"], "observed": {}, "passed": False, "errors": []}
                for target, wanted in case["gold"].items():
                    expected_counts.update(wanted)
                    by_target.setdefault(target, Counter())["count"] += len(wanted)
                try:
                    job = service.run(service.create(payload, source.name, profile_id=profile["id"])["id"])
                    result = job["result"]
                    item["job_id"] = job["id"]
                    item["status"] = result["status"]
                    engine = next(engine for engine in result["engines"] if engine["id"] == "academic-structure")
                    observed: dict[str, list[str]] = {}
                    for check in engine["checks"]:
                        observed.setdefault(check["target"], []).append(check["status"])
                    item["observed"] = observed
                    for target in set(case["gold"]) | set(observed):
                        wanted, actual = case["gold"].get(target, []), observed.get(target, [])
                        observed_counts.update(actual)
                        metric = by_target.setdefault(target, Counter())
                        metric["matched"] += sum(first == second for first, second in zip(wanted, actual))
                        metric["unexpected"] += max(0, len(actual) - len(wanted))
                        if wanted != actual:
                            item["errors"].append("状态与独立标注不一致：" + target)
                    if (result["status"] == "incomplete" or result["input_unchanged"] is not True
                            or result["profile_sha256"] != item["profile_sha256"]
                            or sha256(source) != item["input_sha256"]
                            or (service.jobs_dir / job["id"] / "input.docx").read_bytes() != payload):
                        item["errors"].append("执行未完整完成或输入快照发生变化")
                    item["report_sha256"] = sha256(service.jobs_dir / job["id"] / "report.json")
                    item["passed"] = not item["errors"]
                except (ValueError, OSError, KeyError, StopIteration) as exc:
                    item["errors"].append(type(exc).__name__ + ": " + str(exc))
                records.append(item)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if not already_tracing:
            tracemalloc.stop()
    result = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "scope": manifest["scope"], "dataset_sha256": sha256(MANIFEST), "run_directory": str(run_dir.relative_to(output)),
              "passed": bool(records) and all(item["passed"] for item in records),
              "count": len(records), "passed_count": sum(item["passed"] for item in records),
              "annotation_count": sum(expected_counts.values()), "expected_states": dict(expected_counts),
              "observed_states": dict(observed_counts), "by_target": {key: dict(value) for key, value in sorted(by_target.items())},
              "resources": {"measured": True, "elapsed_seconds": round(time.perf_counter() - started, 6),
                            "peak_python_allocated_bytes": peak, "input_bytes": sum(path.stat().st_size for path in samples.glob("*.docx"))},
              "cases": records}
    write_json(output / "summary.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".formatly/acceptance/academic-structure")
    args = parser.parse_args()
    result = evaluate(args.output.resolve())
    print(json.dumps({key: result[key] for key in ("passed", "count", "passed_count", "annotation_count", "resources")}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
