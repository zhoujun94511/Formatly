"""Run one explicitly supplied document in an isolated school-audit process."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
from types import ModuleType
from typing import Protocol, cast

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from formatly.privacy import redact_local_paths
from formatly.adapters.engine_results import completed_format_findings


class _AuditOne(Protocol):
    def __call__(self, source: Path, kind: str, output: Path, sources: dict, *,
                 pdf: Path | None, pair_status: str, render_word: bool) -> object: ...


class _WriteSummary(Protocol):
    def __call__(self, reports: list[dict], output: Path, provenance: list[dict]) -> object: ...


def _legacy_entries(module: ModuleType) -> tuple[_AuditOne, _WriteSummary]:
    """Type the dynamic module boundary; validate its report separately."""
    audit_entry: object = getattr(module, "audit_one", None)
    summary_entry: object = getattr(module, "write_summary", None)
    if not callable(audit_entry) or not callable(summary_entry):
        raise RuntimeError("专项检测模块缺少 audit_one 或 write_summary 可调用入口")
    return cast(_AuditOne, audit_entry), cast(_WriteSummary, summary_entry)


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def manifest(root: Path) -> dict:
    return {str(p.relative_to(root)): sha(p)
            for folder in ("scripts", "configs") for p in sorted((root / folder).rglob("*"))
            if p.is_file() and p.suffix in {".py", ".ps1", ".json", ".yaml"}}


def _redact_paths(value: str, *paths: Path | None) -> str:
    """Remove local filesystem identities from persisted worker diagnostics."""
    return redact_local_paths(value, *paths)


def engine_failures(report: dict) -> list[str]:
    """Fail closed on changed child-engine states, retaining raw evidence."""
    engines = report.get("engines", {})
    if not isinstance(engines, (dict, list)) or not engines:
        return ["engines.missing"]
    entries = engines.items() if isinstance(engines, dict) else ((str(index), engine) for index, engine in enumerate(engines))
    failures = []
    # "checked"/"screened" describe execution, never a format or visual pass.
    completed = {"completed", "checked", "screened", "passed", "pass", "ok", "success", "ready"}
    for name, engine in entries:
        if not isinstance(engine, dict):
            failures.append(str(name))
            continue
        state = engine.get("status")
        if state in completed:
            continue
        if completed_format_findings(str(name), engine, report):
            continue
        # Optional skipped components are only tolerated when declared optional,
        # and still remain visible as uncovered in the top-level coverage.
        if state in {"skipped", "not_requested", "not_applicable"} and engine.get("required") is False:
            continue
        failures.append(str(name))
    declared = report.get("required_engines", [])
    if isinstance(declared, list) and isinstance(engines, dict):
        failures.extend(str(name) for name in declared if name not in engines)
    return list(dict.fromkeys(failures))


def execute(args) -> None:
    root = (Path(os.environ["FORMATLY_LEGACY_ROOT"]).expanduser()
            if os.environ.get("FORMATLY_LEGACY_ROOT") else
            Path(__file__).resolve().parents[3] / "graduation-format-audit").resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(p.name != "process.log" for p in output.iterdir()):
        raise RuntimeError("输出目录已有检测证据，请使用空目录")
    source = Path(args.input).resolve()
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise ValueError("输入必须为存在的 DOCX 文件")
    pdf = Path(args.pdf).resolve() if args.pdf else None
    if pdf is not None and (not pdf.is_file() or pdf.suffix.lower() != ".pdf"):
        raise ValueError("PDF 必须为存在的 PDF 文件")

    # Retain this check even though the outer plugin already reports its scope.
    # Keep adapter evidence portable and private.  Absolute input paths can
    # contain a person's name, student number, or other local identifiers;
    # they are not needed to reproduce the rule decision because the immutable
    # snapshot is already represented by its digest.
    dump(output / "adapter.json", {
        "id": "configured-school-audit", "scope": "配置的学校与材料范围",
        "scope_declared_by_configuration": True, "default_project_inputs_used": False,
        "default_pdf_used": False,
        "input": {"provided": True, "sha256": sha(source)},
        "pdf": {"provided": pdf is not None, "sha256": sha(pdf) if pdf else None},
        "render_word": args.render_word,
        "legacy_root_configured": bool(os.environ.get("FORMATLY_LEGACY_ROOT")),
        "python": Path(sys.executable).name,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    sources_path = root / "configs" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8-sig"))
    provenance = []
    for name, entry in sources.items():
        # The legacy tool's source manifest may use paths relative to its own
        # root. Resolve those entries against the configured engine directory;
        # absolute paths remain valid for manifests that point elsewhere.
        raw_path = Path(entry["path"]).expanduser()
        path = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
        digest = sha(path) if path.is_file() else None
        provenance.append({"source": name, "expected_sha256": entry["sha256"],
                           "actual_sha256": digest, "matches": digest == entry["sha256"].lower()})
    dump(output / "sources_provenance.json", provenance)
    if not sources or not all(item["matches"] for item in provenance):
        dump(output / "source_version_error.json", provenance)
        raise RuntimeError("学校原件版本或路径不匹配；已停止，请核对规则依据")
    lock = json.loads((root / "configs" / "vendor_lock.json").read_text(encoding="utf-8-sig"))
    changes = []
    vendor_root = (root.parent / "vendor").resolve()
    for name, digest in lock["files"].items():
        path = (vendor_root / name.replace("\\", "/")).resolve()
        if not path.is_relative_to(vendor_root) or not path.is_file() or sha(path) != digest.lower():
            changes.append(name)
    if changes or not lock["files"]:
        dump(output / "vendor_version_error.json", changes)
        raise RuntimeError("专项 vendor 源码与已验证版本不一致")
    dump(output / "vendor_versions.json", {"commits": lock["commits"],
         "checked_files": len(lock["files"]), "matches": True})
    before_manifest = manifest(root)
    dump(output / "implementation_manifest.json", before_manifest)
    config_output = output / "configs"
    config_output.mkdir()
    for config in sorted((root / "configs").iterdir()):
        if config.is_file() and config.suffix in {".json", ".yaml"} and config.name not in {"project.json", "sources.json"}:
            shutil.copy2(config, config_output / config.name)
    # Source provenance already retains hashes. The runtime source manifest
    # contains filesystem locations and is not a downloadable report artifact.
    sys.path.insert(0, str(root / "scripts"))
    legacy_engine = importlib.import_module("run_audit")
    audit_one, write_summary = _legacy_entries(legacy_engine)
    report_value = audit_one(source, args.kind, output / args.kind, sources, pdf=pdf,
                             pair_status="用户提供，配对未核实", render_word=args.render_word)
    if not isinstance(report_value, dict):
        raise RuntimeError("专项检测返回的报告必须为对象")
    report: dict = report_value
    dump(output / "report.json", report)
    write_summary([report], output, provenance)
    if manifest(root) != before_manifest:
        raise RuntimeError("检测期间规则或专项实现发生变化，请用固定版本重新运行")
    # A format error is a completed audit. An engine failure is never a pass.
    incomplete = {"package.semantic", "template.engine", "wordformat.engine", "layout.word_unavailable",
                  "layout.pdf", "thesis.hf_pdf.engine", "thesis.en_abstract_pdf.engine", "integrity.input_changed"}
    failures = [finding for finding in report.get("issues", [])
                if finding.get("rule_id") in incomplete and
                (finding.get("rule_id") != "package.semantic" or
                 report.get("engines", {}).get("semantic", {}).get("status") == "unavailable")]
    failed_engines = engine_failures(report)
    if failures or failed_engines or report.get("original_unchanged") is not True or report.get("snapshot_unchanged") is not True:
        raise RuntimeError("专项检测存在未完成组件或完整性异常：" +
                           ", ".join([item["rule_id"] for item in failures] + failed_engines))
    print(json.dumps({"status": "completed", "kind": args.kind, "report": str(output / "report.json")}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--kind", required=True, choices=("thesis", "intern"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--pdf")
    parser.add_argument("--render-word", action="store_true")
    args = parser.parse_args()
    try:
        execute(args)
        return 0
    except Exception as exc:
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        message = _redact_paths(str(exc), Path(args.input).resolve(),
                                Path(args.pdf).resolve() if args.pdf else None,
                                output)
        trace = _redact_paths(traceback.format_exc(), Path(args.input).resolve(),
                               Path(args.pdf).resolve() if args.pdf else None,
                               output)
        dump(output / "worker_error.json", {"type": type(exc).__name__, "message": message,
                                            "traceback": trace})
        print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

