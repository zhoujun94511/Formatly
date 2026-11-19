"""SQLite repository. Each operation owns its connection; no shared cursors."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3


def now():
    return datetime.now(timezone.utc).isoformat()


def process_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: do not steal work
        try:
            code = wintypes.DWORD()
            return not api.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class JobRepository:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "jobs.sqlite3"
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("任务数据库版本高于当前工具，请使用较新的Formatly，不能覆盖数据库版本")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, filename TEXT NOT NULL,
                profile_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, error TEXT, result TEXT,
                request TEXT NOT NULL, owner_pid INTEGER)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "stage" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN stage TEXT NOT NULL DEFAULT 'queued'")
            if "stage_detail" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN stage_detail TEXT NOT NULL DEFAULT ''")
            if "cancel_requested" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
            if "artifacts_manifest_sha256" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN artifacts_manifest_sha256 TEXT")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=15000")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            raise KeyError("检测任务不存在")
        item = dict(row)
        try:
            for key in ("request", "result"):
                if key in item:
                    item[key] = json.loads(item[key]) if item[key] else None
            if "request" in item and not isinstance(item.get("request"), dict):
                raise ValueError("任务记录结构无效")
            if "result" in item and item.get("result") is not None and not isinstance(item.get("result"), dict):
                raise ValueError("任务记录结构无效")
        except (TypeError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("检测任务记录损坏，请检查数据目录") from exc
        except ValueError as exc:
            raise ValueError("检测任务记录结构无效，请检查数据目录") from exc
        return item

    def create(self, job_id: str, filename: str, profile_id: str, kind: str, request: dict):
        with self.connection() as db:
            db.execute("INSERT INTO jobs(id,status,filename,profile_id,kind,created_at,request) VALUES(?,?,?,?,?,?,?)",
                       (job_id, "queued", filename, profile_id, kind, now(), json.dumps(request, ensure_ascii=False, allow_nan=False)))
        return self.get(job_id)

    def get(self, job_id):
        with self.connection() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def metadata(self, job_id):
        """Keep damaged payloads diagnosable without decoding their JSON."""
        with self.connection() as db:
            row = db.execute("""SELECT id,status,filename,profile_id,kind,created_at,started_at,finished_at,
                error,stage,stage_detail,cancel_requested,artifacts_manifest_sha256 FROM jobs WHERE id=?""", (job_id,)).fetchone()
            if row is None:
                raise KeyError("检测任务不存在")
            return {**dict(row), "result": None, "request": {},
                    "record_warning": "检测任务记录损坏，请恢复备份或重新上传原稿"}

    def seal_artifacts(self, job_id, digest):
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("附件清单摘要无效")
        with self.connection() as db:
            db.execute("UPDATE jobs SET artifacts_manifest_sha256=? WHERE id=? AND status='running' AND cancel_requested=0", (digest, job_id))

    def repair_job(self, operation_key):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE json_valid(request) AND json_extract(request,'$.repair.operation_key')=? LIMIT 1",
                             (operation_key,)).fetchone()
            return self.decode(row) if row is not None else None

    def batch_job(self, batch_id, index):
        with self.connection() as db:
            row = db.execute("""SELECT * FROM jobs WHERE json_valid(request) AND json_extract(request,'$.batch_id')=?
                AND json_extract(request,'$.batch_index')=? AND status IN ('queued','running','completed')
                ORDER BY created_at DESC LIMIT 1""", (batch_id, index)).fetchone()
            return self.decode(row) if row is not None else None

    def page(self, limit=100, offset=0, query="", status=""):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 2 ** 63 - 1:
            raise ValueError("分页参数无效：limit须为1至100，offset有效范围为0至9223372036854775807")
        if status and status not in {"queued", "running", "completed", "failed", "interrupted", "cancelled"}:
            raise ValueError("无效任务状态")
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("搜索文本不能超过200字符")
        where = "WHERE instr(lower(filename),lower(?))>0 AND (?='' OR status=?)"
        args = (query, status, status)
        with self.connection() as db:
            # One read transaction keeps counts and page consistent during completion.
            db.execute("BEGIN")
            total = db.execute("SELECT count(*) FROM jobs " + where, args).fetchone()[0]
            stats = dict(db.execute("""SELECT count(*) AS total,
                coalesce(sum(status='completed'),0) AS completed,
                coalesce(sum(CASE WHEN json_valid(result) THEN
                    coalesce(json_extract(result,'$.document_counts.error'),json_extract(result,'$.counts.error'),0)>0
                    ELSE 0 END),0) AS needs_changes
                FROM jobs""").fetchone())
            rows = db.execute("""SELECT id,status,filename,profile_id,kind,created_at,started_at,finished_at,error,stage,stage_detail,cancel_requested,
                CASE WHEN result IS NOT NULL AND json_valid(result) THEN json_object('status',json_extract(result,'$.status'),
                'counts',json_extract(result,'$.counts'),
                'document_counts',json_extract(result,'$.document_counts'),
                'execution_errors',json_extract(result,'$.execution_errors')) END AS result
                FROM jobs """ + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
            items = [self.decode(row) for row in rows]
        return {"items": items, "total": total, "stats": stats, "offset": offset, "limit": limit}

    def collection_jobs(self, collection_id):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM jobs WHERE json_valid(request) AND json_extract(request,'$.collection_id')=? ORDER BY created_at,id", (collection_id,))
            return [self.decode(row) for row in rows]

    def queued(self):
        with self.connection() as db:
            return [row[0] for row in db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at")]

    def claim(self, job_id):
        with self.connection() as db:
            cursor = db.execute("UPDATE jobs SET status='running',stage='reading',started_at=?,owner_pid=? WHERE id=? AND status='queued' AND cancel_requested=0",
                                (now(), os.getpid(), job_id))
            return cursor.rowcount == 1

    def finish(self, job_id, result=None, error=None):
        status = "failed" if error or (result and result.get("status") == "incomplete") else "completed"
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?,stage='finished',finished_at=?,result=?,error=?,artifacts_manifest_sha256=CASE WHEN ?=0 THEN NULL ELSE artifacts_manifest_sha256 END WHERE id=? AND status='running' AND cancel_requested=0",
                       (status, now(), json.dumps(result, ensure_ascii=False, allow_nan=False) if result else None, error, int(result is not None), job_id))

    def progress(self, job_id, stage, detail=""):
        if stage not in {"reading", "checking", "verifying", "reporting"}:
            raise ValueError("无效任务阶段")
        with self.connection() as db:
            db.execute("UPDATE jobs SET stage=?,stage_detail=? WHERE id=? AND status='running'",
                       (stage, str(detail)[:200], job_id))

    def request_cancel(self, job_id):
        with self.connection() as db:
            if db.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
                raise KeyError("检测任务不存在")
            db.execute("""UPDATE jobs SET cancel_requested=1,
                status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                stage=CASE WHEN status='queued' THEN 'cancelled' ELSE stage END,
                finished_at=CASE WHEN status='queued' THEN ? ELSE finished_at END
                WHERE id=? AND status IN ('queued','running')""", (now(), job_id))
        return self.get(job_id)

    def complete_cancel(self, job_id):
        with self.connection() as db:
            db.execute("""UPDATE jobs SET status='cancelled',stage='cancelled',finished_at=?,result=NULL,artifacts_manifest_sha256=NULL,
                error='任务已取消，未形成完整检测结论'
                WHERE id=? AND status='running' AND cancel_requested=1""", (now(), job_id))

    def recover(self):
        with self.connection() as db:
            rows = list(db.execute("SELECT id,owner_pid FROM jobs WHERE status='running'"))
            for row in rows:
                if not row["owner_pid"] or not process_alive(row["owner_pid"]):
                    db.execute("""UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,
                               stage=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,
                               finished_at=?,error=? WHERE id=? AND status='running'""",
                               (now(), "上一次检测进程已退出，可使用原规则快照重新检测", row["id"]))

