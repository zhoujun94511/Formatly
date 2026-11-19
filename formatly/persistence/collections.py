"""Persistent material sets and conservative cross-document field comparison."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
import uuid

from ..files import write_json
from ..plugins.fields import FIELD_LABELS, normalize_field
from .locks import write_lock

KINDS = ("thesis", "intern", "certificate")
MAX_RECORD_BYTES = 4 * 1024 * 1024


class CollectionStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "collections"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("材料集合标识无效")
        return self.root / (identity + ".json")

    def _save(self, value):
        encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RECORD_BYTES:
            raise ValueError("材料集合记录将超过4MiB，未保存；请新建材料集合")
        write_json(self._path(value["id"]), value)

    def list(self):
        return self.list_with_warnings()["items"]

    def list_errors(self):
        return self.list_with_warnings()["warnings"]

    def list_with_warnings(self):
        items, warnings = [], []
        for path in sorted(self.root.glob("*.json")):
            identity = path.stem
            try:
                items.append(self.get(identity))
            except (OSError, ValueError, KeyError):
                # User-controlled file names can contain personal details.
                label = identity if re.fullmatch(r"[a-f0-9]{32}", identity) else "无效集合记录"
                warnings.append({"id": label, "file": label,
                                 "message": "材料集合记录损坏或不可读取；原文件已保留，请恢复备份或重新创建。"})
        return {"items": items, "warnings": warnings}

    def get(self, identity):
        path = self._path(identity)
        if not path.is_file():
            raise KeyError("材料集合不存在")
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                raise ValueError("材料集合记录超过4MiB，无法读取")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("材料集合记录损坏，请重新创建集合") from exc
        if (not isinstance(value, dict) or value.get("id") != identity
                or not isinstance(value.get("name"), str)
                or not isinstance(value.get("required_kinds"), list)
                or not value["required_kinds"]
                or any(kind not in KINDS for kind in value["required_kinds"])
                or not isinstance(value.get("job_ids"), list)
                or any(not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id)
                       for job_id in value["job_ids"])):
            raise ValueError("材料集合记录结构无效，请重新创建集合")
        return value

    def create(self, name, required_kinds=None):
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("集合名称必填且最多120字符")
        required = list(KINDS) if required_kinds is None else required_kinds
        if not isinstance(required, list) or not required or any(kind not in KINDS for kind in required):
            raise ValueError("集合至少选择一种有效材料类型")
        value = {"id": uuid.uuid4().hex, "name": name.strip(), "required_kinds": list(dict.fromkeys(required)),
                 "job_ids": [], "created_at": datetime.now(timezone.utc).isoformat()}
        self._save(value)
        return value

    def add_job(self, identity, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("任务标识无效")
        with write_lock(self.root, self._lock):
            value = self.get(identity)
            if job_id not in value["job_ids"]:
                value["job_ids"].append(job_id)
                value["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save(value)
            return value


def evaluate(collection, jobs):
    """Compare only supplied completed records belonging to this collection.

    Repeat uploads of one kind are revisions. Only its latest task is eligible;
    if it failed or remains busy, an older success cannot conceal that state.
    All excluded revisions remain visible.
    """
    identities = list(dict.fromkeys(collection.get("job_ids", [])))
    supplied = {job["id"]: job for job in jobs if job.get("id") in identities}
    items = [supplied.get(identity, {"id": identity, "status": "interrupted", "error": "关联任务不存在"})
             for identity in identities]
    checks, selected, excluded = [], {}, []
    for job in items:
        if job.get("kind") not in KINDS:
            checks.append({"rule_id": "materials.integrity", "status": "manual", "job_id": job["id"],
                           "message": "关联任务不存在或材料类型不可读取，须核对材料集合完整性",
                           "expected": "全部关联任务及材料类型可读取",
                           "actual": {"task_status": job.get("status"), "kind": job.get("kind"), "error": job.get("error")},
                           "source": "材料集合的关联任务完整性"})
    for kind in collection.get("required_kinds", KINDS):
        candidates = [job for job in items if job.get("kind") == kind]
        newest = max(candidates, key=lambda item: (item.get("created_at", ""), item.get("id", "")), default=None)
        if newest is None:
            checks.append({"rule_id": "materials." + kind, "status": "manual", "message": "缺少要求的材料类型", "kind": kind,
                           "expected": kind, "actual": None, "source": "材料集合的必需类型"})
        elif newest.get("status") != "completed" or not isinstance(newest.get("result"), dict) or not newest["result"] or newest["result"].get("status") == "incomplete":
            checks.append({"rule_id": "materials." + kind, "status": "manual", "message": "最新材料检测尚未成功完成，不能使用较早结果替代", "kind": kind, "job_id": newest["id"],
                           "expected": "最新任务完整完成检测", "actual": {"task_status": newest.get("status"), "result_status": newest["result"].get("status") if isinstance(newest.get("result"), dict) else None}, "source": "材料集合的任务版本"})
        else:
            selected[kind] = newest
        excluded.extend(job["id"] for job in candidates if newest and job["id"] != newest["id"])
    selected_jobs = list(selected.values())
    for key in FIELD_LABELS:
        values, missing = [], []
        for job in selected_jobs:
            engines = job["result"].get("engines", [])
            if isinstance(engines, dict):
                engines = [{"id": identity, **engine} for identity, engine in engines.items()]
            engine = next((engine for engine in engines if engine.get("id") == "document-fields" and engine.get("status") == "completed"), {})
            field = engine.get("evidence", {}).get("fields", {}).get(key, {})
            if field.get("status") != "resolved" or not isinstance(field.get("value"), str):
                missing.append(job["id"])
            else:
                values.append({"job_id": job["id"], "kind": job["kind"], "value": normalize_field(key, field["value"]),
                               "locations": field.get("locations", [])})
        unique = {item["value"] for item in values}
        if len(unique) > 1:
            status, message = "failed", "材料之间的字段值不一致"
        elif missing or len(values) < 2:
            status, message = "manual", "没有至少两份完整且唯一的字段证据，不能确认一致"
        else:
            status, message = "passed", "已提取字段在所选材料中一致"
        checks.append({"rule_id": "consistency." + key, "field": key, "status": status, "message": message,
                       "values": values, "missing_job_ids": missing, "expected": "至少两份材料的唯一字段值一致",
                       "actual": {"values": values, "missing_job_ids": missing}, "source": "材料集合：真实字段提取证据"})
    summary = {status: sum(check["status"] == status for check in checks) for status in ("passed", "failed", "manual")}
    status = "needs_changes" if summary["failed"] else "review_required" if summary["manual"] else "passed"
    return {**collection, "items": items, "selected_job_ids": [job["id"] for job in selected_jobs],
            "excluded_revision_ids": excluded, "checks": checks, "summary": summary, "status": status,
            "scope": "仅核对明确提取的标签字段一致性；不证明各材料真实性或学校全部要求已满足"}
