"""Idempotent batches composed of ordinary independent audit jobs."""
from __future__ import annotations

import hashlib
import json
import re

from ..files import MAX_FILE_BYTES, write_json

MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 80 * 1024 * 1024
MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def _read_receipt(path, batch_id):
    """Read a local batch receipt without leaking parser errors to a worker thread."""
    try:
        if path.stat().st_size > MAX_RECEIPT_BYTES:
            raise ValueError("批次记录超过4MiB，无法恢复")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("批次记录损坏，请使用新的 batch_key 重新提交") from exc
    if (not isinstance(value, dict) or value.get("batch_id") != batch_id
            or not isinstance(value.get("fingerprint"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["fingerprint"])
            or not isinstance(value.get("items"), list) or len(value["items"]) > MAX_BATCH_FILES):
        raise ValueError("批次记录结构无效，请使用新的 batch_key 重新提交")
    return value


def create_batch(service, documents, profile_id="generic", kind="thesis", collection_id=None, batch_key=None, scope_bindings=None):
    if not isinstance(batch_key, str) or not re.fullmatch(r"[a-f0-9]{32}", batch_key):
        raise ValueError("批量请求须提供32位小写十六进制 batch_key")
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_BATCH_FILES:
        raise ValueError("每批须提供1至20份原稿")
    if any(not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str)
           or not isinstance(item[1], bytes) for item in documents):
        raise ValueError("批量原稿须包含文件名和原始字节")
    if sum(len(data) for _, data in documents) > MAX_BATCH_BYTES:
        raise ValueError("每批原稿合计不能超过80MiB")
    if scope_bindings is not None and (not isinstance(scope_bindings, list) or len(scope_bindings) != len(documents)
            or any(value is not None and not isinstance(value, dict) for value in scope_bindings)):
        raise ValueError("批量范围确认须为与原稿顺序、数量一致的数组，每份原稿单独确认")
    if scope_bindings is not None and len(json.dumps(scope_bindings, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 1024 * 1024:
        raise ValueError("批量范围确认超过1MiB")
    fingerprint_value = {"profile_id": profile_id, "kind": kind,
        "collection_id": collection_id, "files": [(name, hashlib.sha256(data).hexdigest()) for name, data in documents]}
    if scope_bindings is not None:
        fingerprint_value["scope_bindings"] = scope_bindings
    fingerprint = hashlib.sha256(json.dumps(fingerprint_value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
    root = service.data_dir / "batches"
    root.mkdir(exist_ok=True)
    path = root / (batch_key + ".json")
    with service.batch_write_guard():
        receipt = _read_receipt(path, batch_key) if path.exists() else {
            "batch_id": batch_key, "fingerprint": fingerprint, "items": [],
            "profile_snapshot": service.profiles.get(profile_id)}
        if receipt["fingerprint"] != fingerprint:
            raise ValueError("该批次标识已用于其他文件或方案，请创建新批次")
        # Persist identity and the immutable rule snapshot before creating any job.
        # A crash between job persistence and receipt append remains recoverable.
        write_json(path, receipt)
        for index, (filename, document) in enumerate(documents):
            if index < len(receipt["items"]):
                continue
            item = {"index": index, "filename": filename}
            try:
                if not 0 < len(document) <= MAX_FILE_BYTES:
                    raise ValueError("原稿为空或超过40MiB")
                # Recover a job persisted before a previous receipt write failed.
                record = service.repository.batch_job(batch_key, index)
                if record and record['request'].get('batch_fingerprint') != fingerprint:
                    raise ValueError('批次恢复记录与当前原稿不一致，未复用历史任务')
                job = service.public(record) if record else service.create(document, filename,
                    profile_id=profile_id, kind=kind, collection_id=collection_id,
                    profile_snapshot=receipt['profile_snapshot'], batch_id=batch_key, batch_index=index,
                    batch_fingerprint=fingerprint, scope_bindings=scope_bindings[index] if scope_bindings is not None else None)
                item["job_id"] = job["id"]
            except (ValueError, KeyError) as exc:
                item["error"] = str(exc).strip("'")
            receipt["items"].append(item)
            write_json(path, receipt)
    return _response(service, receipt, schedule=True)


def get_batch(service, batch_id):
    if not isinstance(batch_id, str) or not re.fullmatch(r"[a-f0-9]{32}", batch_id):
        raise ValueError("批次标识无效")
    path = service.data_dir / "batches" / (batch_id + ".json")
    if not path.is_file():
        raise KeyError("批次不存在")
    return _response(service, _read_receipt(path, batch_id))


def _response(service, receipt, schedule=False):
    items = []
    for item in receipt["items"]:
        if "job_id" in item:
            job = service.get(item["job_id"])
            if schedule and job["status"] == "queued":
                service.schedule(job["id"])
            items.append({**item, "job": job})
        else:
            items.append(item)
    return {"batch_id": receipt['batch_id'], "items": items}
