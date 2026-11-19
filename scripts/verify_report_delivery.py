"""Download a real job report over HTTP, then stop the owned service.

The output contains a private document snapshot and must stay outside version
control. This checks report delivery, not school-rule accuracy or expert review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
import threading
from typing import Any
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.application.service import AuditService
from formatly.application.reports import REPORT_TEMPLATE
from formatly.interfaces.http import make_server


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def port_is_closed(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", port)) != 0


def verify_delivery(source: Path, output: Path, profile_path: Path | None = None,
                    kind: str = "thesis") -> dict:
    """Preserve the original and expose only an anonymous filename in the report."""
    source = source.resolve(strict=True)
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("验收输出目录必须为空，避免覆盖已有证据")
    original = source.read_bytes()
    original_hash = digest(original)
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path else None
    output.mkdir(parents=True, exist_ok=True)
    offline = output / "offline"
    offline.mkdir()
    service = AuditService(output / "service")
    server = None
    thread = None
    port: int | None = None
    anonymous_filename = "document" + source.suffix.lower()
    evidence: dict[str, Any] = {"schema": "formatly.report-delivery.v1",
                "scope": "report_delivery_only_not_school_accuracy",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "input_sha256": original_hash, "kind": kind,
                "report_template_sha256": digest(REPORT_TEMPLATE.read_bytes()),
                "anonymous_filename": anonymous_filename,
                "http_downloads": []}
    try:
        job = service.create(original, anonymous_filename, kind=kind,
                             profile_snapshot=profile)
        service.run(job["id"])
        job = service.get(job["id"])
        if job["status"] != "completed":
            raise RuntimeError("验收任务未完成，请检查输出目录中的任务记录")
        job_dir = service.jobs_dir / job["id"]
        result = json.loads((job_dir / "report.json").read_text(encoding="utf-8"))
        if result.get("input_sha256") != original_hash or result.get("input_unchanged") is not True:
            raise RuntimeError("报告输入哈希或快照完整性未通过")
        evidence.update(job_id=job["id"], profile_sha256=result.get("profile_sha256"),
                        verdict=result["status"], counts=result["counts"],
                        issue_count=len(result["issues"]),
                        input_snapshot_unchanged=True,
                        execution_errors=result.get("execution_errors", 0))
        if evidence["execution_errors"]:
            raise RuntimeError("任务有执行异常，不能作为报告交付验收样本")
        server = make_server(service, host="127.0.0.1", port=0)
        port = server.server_port
        evidence["service_host"] = "127.0.0.1"
        evidence["service_port"] = port
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        for filename in ("report.html", "report.json"):
            url = f"http://127.0.0.1:{port}/api/jobs/{job['id']}/artifacts/{filename}"
            with opener.open(url, timeout=15) as response:
                payload = response.read()
                disposition = response.headers.get("Content-Disposition", "")
                if response.status != 200 or "attachment" not in disposition.lower():
                    raise RuntimeError("报告下载没有返回成功的附件响应")
                if digest(payload) != digest((job_dir / filename).read_bytes()):
                    raise RuntimeError("HTTP 下载与任务报告哈希不一致")
                target = offline / filename if filename.endswith("html") else output / filename
                target.write_bytes(payload)
                evidence["http_downloads"].append({
                    "filename": filename, "status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "attachment": True, "sha256": digest(payload),
                    "bytes": len(payload), "saved_as": target.relative_to(output).as_posix()})
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        service.close()
        evidence["original_unchanged"] = digest(source.read_bytes()) == original_hash
        evidence["server_stopped"] = (thread is None or not thread.is_alive()) and (
            port is None or port_is_closed(port))
        evidence["offline_folder_files"] = sorted(path.name for path in offline.iterdir())
        (output / "delivery.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    if not evidence["original_unchanged"] or not evidence["server_stopped"]:
        raise RuntimeError("原件完整性或自建服务停止状态未通过")
    return evidence


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", type=Path, help="Optional confirmed profile JSON; defaults to basic preflight")
    parser.add_argument("--kind", choices=("thesis", "intern", "certificate"), default="thesis")
    args = parser.parse_args(argv)
    evidence = verify_delivery(args.input, args.output, args.profile, args.kind)
    print(json.dumps({"job_id": evidence["job_id"], "input_sha256": evidence["input_sha256"],
                      "issue_count": evidence["issue_count"], "server_stopped": evidence["server_stopped"],
                      "original_unchanged": evidence["original_unchanged"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
