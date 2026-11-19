"""Snapshot-bound human notes, stored independently of automatic reports."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import Lock

from ..application.evidence import issue_key, validate_snapshot
from ..files import write_json
from .locks import write_lock

MAX_RECORD_BYTES = 4 * 1024 * 1024


class ReviewVersionConflict(ValueError):
    pass


class ReviewStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "reviews"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _path(self, job: dict) -> Path:
        if not isinstance(job.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", job["id"]):
            raise ValueError("检测任务标识无效")
        return self.root / (job["id"] + ".json")

    def get(self, job: dict) -> dict:
        result = validate_snapshot(job)
        path = self._path(job)
        binding = {"job_id": job["id"], "input_sha256": result["input_sha256"], "profile_sha256": result["profile_sha256"]}
        if not path.is_file():
            return {**binding, "version": 0, "items": {}}
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                raise ValueError("复核记录超过4MiB，无法读取")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("复核记录损坏，请重新读取报告后再保存") from exc
        if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] < 0
                or not isinstance(value.get("items"), dict) or not isinstance(value.get("history", []), list)
                or len(value.get("history", [])) > 10000):
            raise ValueError("复核记录结构无效，请重新读取报告后再保存")
        if any(value.get(key) != expected for key, expected in binding.items()):
            raise ValueError("复核记录与当前报告快照不匹配，请重新检测")
        return value

    def save(self, job: dict, payload: dict) -> dict:
        result = validate_snapshot(job)
        if not isinstance(payload, dict) or set(payload) - {"version", "issue_key", "status", "note", "input_sha256", "profile_sha256"}:
            raise ValueError("复核记录字段无效")
        if type(payload.get("version")) is not int or payload["version"] < 0:
            raise ValueError("请提供复核记录版本")
        if any(payload.get(key) != result[key] for key in ("input_sha256", "profile_sha256")):
            raise ValueError("复核记录快照已过期，请重新读取报告")
        keys = {issue_key(result, index) for index in range(len(result.get("issues", [])))}
        identity, status, note = payload.get("issue_key"), payload.get("status"), payload.get("note", "")
        if (not isinstance(identity, str) or not isinstance(status, str) or identity not in keys
                or status not in {"pending", "checked", "suspected_false_positive"}):
            raise ValueError("请选择有效问题和复核状态")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValueError("复核备注最多2000字符")
        with write_lock(self.root, self._lock):
            value = self.get(job)
            if value["version"] != payload["version"]:
                raise ReviewVersionConflict("复核意见已被其他窗口更新，请先读取最新记录；当前输入仍保留")
            updated_at = datetime.now(timezone.utc).isoformat()
            record = {"issue_key": identity, "status": status, "note": note.strip(), "updated_at": updated_at}
            history = list(value.get("history", []))
            history.append(record)
            if len(history) > 10000:
                raise ValueError("复核历史已达上限，请另建检测记录")
            value.update(version=value["version"] + 1, updated_at=updated_at, history=history)
            value["items"][identity] = record
            encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            if len(encoded) > MAX_RECORD_BYTES:
                raise ValueError("复核记录将超过4MiB，未保存；请缩短备注或另建检测记录")
            write_json(self._path(job), value)
            return value
