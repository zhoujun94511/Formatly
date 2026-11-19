"""Application layer: snapshots, jobs, reports and diagnostics. No HTTP coupling."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
from typing import Any, Mapping
import uuid

from .. import __version__
from ..domain import AuditContext
from ..files import MAX_FILE_BYTES, atomic_write, safe_child, sha256, write_json
from .pipeline import execute
from ..persistence.profiles import ProfileStore, validate_profile
from ..plugins.registry import PluginRegistry
from .reports import render_reports
from ..persistence.jobs import JobRepository
from ..persistence.schools import SchoolStore
from ..persistence.collections import CollectionStore, evaluate as evaluate_collection
from ..documents import document_format, probe_pdf, probe_ocr
from ..documents.office import probe_office, render_office
from ..persistence.locks import write_lock
from .repairs import apply_repair_plan, build_repair_plan
from .job_control import JobCancelled, checkpoint
from ..persistence.reviews import ReviewStore
from ..privacy import public_ocr_information, redact_local_paths
from .document_scopes import DocumentPreviewStore, derive_profile, document_scope_digest, profile_digest, scope_capabilities, scope_requirements

FINAL_REPORT_FILES = frozenset({'report.json', 'report.html', 'report.md', 'artifacts-manifest.json'})


def platform_data_dir(os_name: str, platform: str, env: Mapping[str, str], home: Path) -> Path:
    """Pick the per-user data directory for Windows, macOS, or Linux."""
    configured = env.get("FORMATLY_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os_name == "nt":
        return Path(env.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Formatly"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Formatly"
    return Path(env.get("XDG_DATA_HOME", home / ".local" / "share")) / "formatly"


def default_data_dir():
    return platform_data_dir(os.name, sys.platform, os.environ, Path.home())


def _retry_snapshot(path: Path, expected_digest: str, message: str) -> bytes:
    """Return bounded bytes whose digest matches the original task record."""
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise ValueError(message) from exc
    if not 0 < len(data) <= MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != expected_digest:
        raise ValueError(message)
    return data


def invalidate_original(result, rule_id, message, location):
    """Keep the verdict, coverage and counters consistent after source rechecks."""
    result["status"] = "incomplete"
    result["issues"].append({"rule_id": rule_id, "level": "error", "message": message,
        "location": location, "plugin": "core", "source": "输入哈希", "category": "integrity"})
    result["counts"]["error"] += 1
    result["execution_errors"] = result.get("execution_errors", 0) + 1
    coverage = result.get("coverage")
    if coverage is not None:
        coverage["complete"] = False
        coverage.setdefault("checks", []).append({"rule_id": rule_id, "status": "error", "label": message,
            "location": location, "source": "输入哈希", "kind": "integrity", "expected": "哈希未变", "actual": "发生变化或不可读"})
        summary = coverage.setdefault("summary", {})
        summary["error"] = summary.get("error", 0) + 1


class AuditService:
    def __init__(self, data_dir=None, registry=None):
        self.data_dir = Path(data_dir or default_data_dir()).resolve()
        self.jobs_dir = self.data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.repository = JobRepository(self.data_dir)
        self.repository.recover()
        self.profiles = ProfileStore(self.data_dir)
        self.registry = registry or PluginRegistry(data_dir=self.data_dir)
        self.schools = SchoolStore(self.data_dir)
        self.collections = CollectionStore(self.data_dir)
        self.reviews = ReviewStore(self.data_dir)
        self.document_previews = DocumentPreviewStore(self.data_dir)
        self._executor: ThreadPoolExecutor | None = None
        self._worker_lock = threading.Lock()
        self._repair_lock = threading.Lock()
        self._batch_lock = threading.Lock()
        self._scheduled = set()
        # Keep caller-owned source paths in memory only. Persisted task
        # records contain the copied snapshot and its hash, never a local
        # username or filesystem path.
        self._original_sources: dict[str, tuple[Path | None, Path | None]] = {}
        self._closed = False

    def _start_worker_locked(self):
        if self._closed:
            raise RuntimeError("检测服务已关闭，无法提交任务")
        if self._executor is None:
            # Serial per service: Word/WPS COM and school-engine fonts are process-global.
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="formatly")
            return True
        return False

    def _schedule_locked(self, job_id):
        if job_id in self._scheduled:
            return
        executor = self._executor
        if executor is None:
            raise RuntimeError("检测任务执行器尚未启动")
        self._scheduled.add(job_id)
        try:
            executor.submit(self._run_scheduled, job_id)
        except Exception:
            self._scheduled.discard(job_id)
            raise

    def start_worker(self):
        with self._worker_lock:
            self._start_worker_locked()
            for job_id in self.repository.queued():
                self._schedule_locked(job_id)

    def schedule(self, job_id):
        with self._worker_lock:
            if self._start_worker_locked():
                for queued_id in self.repository.queued():
                    self._schedule_locked(queued_id)
            self._schedule_locked(job_id)

    def _run_scheduled(self, job_id):
        try:
            self.run(job_id)
        finally:
            with self._worker_lock:
                self._scheduled.discard(job_id)

    def close(self):
        with self._worker_lock:
            self._closed = True
            executor = self._executor
        if executor:
            executor.shutdown(wait=True, cancel_futures=False)
            with self._worker_lock:
                if self._executor is executor:
                    self._executor = None

    def save_profile(self, value):
        value = validate_profile(value)
        for plugin in value["plugins"]:
            self.registry.get(plugin)
        self.registry.validate_settings(value)
        return self.profiles.save(value)

    def profile_preflight(self, profile_id, kind="thesis", input_format="docx"):
        if kind not in {"thesis", "intern", "certificate"}:
            raise ValueError("文档类型仅支持 thesis、intern 或 certificate")
        profile = validate_profile(self.profiles.get(profile_id))
        return {**self.registry.preflight(profile, kind, input_format),
                "document_scope": scope_capabilities(profile, kind, input_format)}

    def document_preview(self, document, filename, profile_id="generic", kind="thesis"):
        preflight = self.profile_preflight(profile_id, kind, "docx")
        if not preflight["available"]:
            raise ValueError("所选方案或材料类型当前不可用")
        return self.document_previews.create(document, filename, validate_profile(self.profiles.get(profile_id)), kind)

    def document_preview_styles(self, identity, query="", offset=0, limit=10):
        return self.document_previews.catalog(identity, "styles", query=query, offset=offset, limit=limit)

    def document_preview_sections(self, identity, offset=0, limit=10):
        return self.document_previews.catalog(identity, "sections", offset=offset, limit=limit)

    def discard_document_preview(self, identity):
        return self.document_previews.discard(identity)

    @staticmethod
    def capabilities():
        available, reason = probe_pdf()
        ocr = probe_ocr()
        public_ocr = public_ocr_information(ocr)
        return {"formats": ["docx", "pdf", "txt", "md", "json"],
                "pdf": {"available": available, "reason": reason}, "ocr": public_ocr,
                "office": probe_office(),
                "limits": {"file_bytes": MAX_FILE_BYTES, "extracted_text_bytes": 1024 * 1024}}

    def confirm_school(self, school_id, requirements, expected_version=None):
        def validate_school_profile(value):
            profile = validate_profile(value)
            self.registry.validate_settings(profile)
            return profile
        profiles = self.schools.confirm(school_id, requirements, validate_profile=validate_school_profile,
                                       expected_version=expected_version,
                                       publish_profiles=lambda batch: [self.save_profile(profile) for profile in batch])
        return {"school": self.schools.get(school_id), "profiles": profiles}

    def collection(self, collection_id):
        collection = self.collections.get(collection_id)
        # The transactional request is authoritative if an index-file update
        # was interrupted, or another process appended a collection member.
        records = self.repository.collection_jobs(collection_id)
        jobs = [self.public(job) for job in records]
        known_ids = {job["id"] for job in jobs}
        for job_id in collection.get("job_ids", []):
            if job_id in known_ids:
                continue
            try:
                jobs.append(self.get(job_id))
            except KeyError:
                jobs.append({"id": job_id, "status": "interrupted", "error": "关联任务不存在"})
        collection["job_ids"] = list(dict.fromkeys([*collection.get("job_ids", []), *known_ids]))
        return evaluate_collection(collection, jobs)

    def create(self, document: bytes, filename: str, profile_id="generic", kind="thesis", pdf=None,
               render_word=False, profile_snapshot=None, original_path=None, original_pdf_path=None,
               collection_id=None, repair: dict | None = None, revision_of_job_id=None,
               batch_id=None, batch_index=None, batch_fingerprint=None,
               preview_id=None, scope_bindings=None):
        if kind not in {"thesis", "intern", "certificate"}:
            raise ValueError("文档类型仅支持 thesis、intern 或 certificate")
        if not isinstance(filename, str):
            raise ValueError("文档文件名无效")
        filename = Path(filename.replace("\\", "/")).name
        input_format = document_format(filename)
        if not isinstance(document, bytes) or (not 0 < len(document) <= MAX_FILE_BYTES and not (preview_id is not None and document == b"")):
            raise ValueError("文档为空或超过40MB限制")
        if input_format == "pdf" and not document.startswith(b"%PDF-"):
            raise ValueError("PDF原稿签名无效")
        if input_format != "docx" and (pdf is not None or render_word):
            raise ValueError("配对 PDF 和 Word/WPS 导出仅适用于 DOCX 原稿")
        if pdf is not None and (not 0 < len(pdf) <= MAX_FILE_BYTES or not pdf.startswith(b"%PDF-")):
            raise ValueError("PDF为空、格式错误或超过40MB限制")
        profile = validate_profile(profile_snapshot if profile_snapshot is not None else self.profiles.get(profile_id))
        if preview_id is not None:
            if scope_bindings is None and scope_requirements(profile, kind):
                raise ValueError("请确认原稿范围，或明确选择暂不匹配")
            with self.document_previews.consume(preview_id, profile, kind) as (preview, copied):
                if document and hashlib.sha256(document).hexdigest() != preview["input_sha256"]:
                    raise ValueError("原稿已变化，请重新确认范围")
                return self.create(copied, preview["filename"], profile_id=profile_id, kind=kind, pdf=pdf,
                    render_word=render_word, profile_snapshot=profile, original_path=original_path,
                    original_pdf_path=original_pdf_path, collection_id=collection_id, repair=repair,
                    revision_of_job_id=revision_of_job_id, batch_id=batch_id, batch_index=batch_index,
                    batch_fingerprint=batch_fingerprint, scope_bindings=scope_bindings)
        source_profile = profile
        if scope_bindings is not None or profile.get("school") and scope_requirements(profile, kind):
            with self.document_previews.temporary_document(document, filename) as temporary:
                profile, scope_bindings = derive_profile(profile, kind, temporary, scope_bindings)
        for plugin_id in profile["plugins"]:
            self.registry.get(plugin_id)
        self.registry.validate_settings(profile)
        preflight = self.registry.preflight(profile, kind, input_format)
        if not preflight["available"]:
            reasons = [item.get("reason", "") for item in preflight.get("plugins", []) if not item.get("available")]
            raise ValueError("方案当前不可执行：" + "；".join(reasons or preflight.get("warnings", []) or ["文档类型不适用"]))
        if collection_id:
            self.collections.get(collection_id)
        if render_word and "legacy-school" not in profile["plugins"]:
            if pdf is not None:
                raise ValueError("自行提供配对 PDF 和本机生成 PDF 请选择一项")
            capability = probe_office()
            if not capability["available"]:
                raise ValueError(capability["reason"])
        if revision_of_job_id:
            parent = self.repository.get(revision_of_job_id)
            if parent["status"] in {"queued", "running"}:
                raise ValueError("原任务尚未完成，不能建立修改稿复检")
            if parent["kind"] != kind:
                raise ValueError("修改稿的材料类型必须与原任务一致")
        job_id = uuid.uuid4().hex
        directory = self.jobs_dir / job_id
        directory.mkdir()
        persisted = False
        try:
            input_path = directory / ("input." + input_format)
            atomic_write(input_path, document)
            if pdf is not None:
                atomic_write(directory / "input.pdf", pdf)
            write_json(directory / "profile.json", profile)
            request = {"profile": profile, "pdf": pdf is not None, "render_word": bool(render_word),
                       "artifacts_manifest_version": 1,
                       "input_format": input_format, "input_sha256": sha256(input_path),
                       "pdf_sha256": sha256(directory / "input.pdf") if pdf is not None else None,
                       "original_path": None,
                       "original_pdf_path": None,
                       "collection_id": collection_id or None}
            if scope_bindings is not None:
                request.update(scope_bindings=scope_bindings, source_profile=source_profile,
                               source_profile_sha256=profile_digest(source_profile))
                write_json(directory / "scope-bindings.json", scope_bindings)
                write_json(directory / "source-profile.json", source_profile)
            if revision_of_job_id:
                request["revision_of_job_id"] = revision_of_job_id
            if batch_id:
                request.update(batch_id=batch_id, batch_index=batch_index, batch_fingerprint=batch_fingerprint)
            if repair is not None:
                if input_format != "docx" or repair.get("output_sha256") != request["input_sha256"]:
                    raise ValueError("修复副本与修改记录不一致")
                request["repair"] = json.loads(json.dumps(repair, ensure_ascii=False, allow_nan=False))
                atomic_write(directory / "repaired.docx", document)
                write_json(directory / "repair.json", request["repair"])
            write_json(directory / "request.json", request)
            job = self.repository.create(job_id, filename, profile["id"], kind, request)
            persisted = True
            if original_path is not None or original_pdf_path is not None:
                self._original_sources[job_id] = (
                    Path(original_path).resolve() if original_path is not None else None,
                    Path(original_pdf_path).resolve() if original_pdf_path is not None else None,
                )
            if collection_id:
                self.collections.add_job(collection_id, job_id)
            return self.public(job)
        except Exception as exc:
            if persisted:
                if self.repository.claim(job_id):
                    self.repository.finish(job_id, error="建立材料关联失败：" + redact_local_paths(str(exc)))
            else:
                shutil.rmtree(directory)
            raise

    def create_from_path(self, path, **kwargs):
        path = Path(path).resolve()
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("输入文档不存在或超过40MB限制")
        pdf_value: object = kwargs.pop("pdf_path", None)
        pdf_path: Path | None = None
        pdf_data: bytes | None = None
        if pdf_value is not None and pdf_value != "":
            if not isinstance(pdf_value, (str, os.PathLike)):
                raise ValueError("PDF 路径须为字符串或文件系统路径")
            pdf_filename = os.fspath(pdf_value)
            if not isinstance(pdf_filename, str):
                raise ValueError("PDF 路径须使用文本，不能使用字节路径")
            pdf_path = Path(pdf_filename).resolve()
            if not pdf_path.is_file() or pdf_path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("PDF不存在或超过40MB限制")
            pdf_data = pdf_path.read_bytes()
        return self.create(path.read_bytes(), path.name, pdf=pdf_data,
                           original_path=path, original_pdf_path=pdf_path, **kwargs)

    def run(self, job_id):
        if not self.repository.claim(job_id):
            return self.get(job_id)
        directory = self.jobs_dir / job_id
        try:
            job = self.repository.get(job_id)
            request = job["request"]
            input_format = request.get("input_format", "docx")
            if (input_format not in {"docx", "pdf", "txt", "md", "json"}
                    or not isinstance(request.get("profile"), dict)
                    or not isinstance(request.get("input_sha256"), str)
                    or type(request.get("pdf")) is not bool or type(request.get("render_word")) is not bool):
                raise ValueError("检测任务请求结构无效，请重新上传原稿")
            input_path = directory / ("input." + input_format)
            if sha256(input_path) != request["input_sha256"]:
                raise ValueError("输入快照已被修改，不能继续检测")
            if request["pdf"] and sha256(directory / "input.pdf") != request["pdf_sha256"]:
                raise ValueError("PDF快照已被修改，不能继续检测")
            if request.get("scope_bindings") is not None:
                if (request["scope_bindings"].get("input_sha256") != request["input_sha256"]
                        or request["scope_bindings"].get("profile_sha256") != request["source_profile_sha256"]
                        or profile_digest(request["source_profile"]) != request["source_profile_sha256"]
                        or json.loads((directory / "scope-bindings.json").read_text(encoding="utf-8")) != request["scope_bindings"]
                        or json.loads((directory / "source-profile.json").read_text(encoding="utf-8")) != request["source_profile"]):
                    raise ValueError("原稿范围确认快照已变化，不能继续检测")
                derived, _ = derive_profile(validate_profile(request["source_profile"]), job["kind"], input_path, request["scope_bindings"])
                if derived != request["profile"]:
                    raise ValueError("本次执行方案与原稿范围确认不一致")
            if request.get("repair") and (request["repair"].get("output_sha256") != request["input_sha256"]
                    or sha256(directory / "repaired.docx") != request["input_sha256"]):
                raise ValueError("修复副本与复检输入不一致，不能继续检测")
            write_json(directory / "runtime.json", {"version": __version__, "profile": request["profile"],
                        "packages": sorted({d.metadata["Name"]: d.version for d in importlib.metadata.distributions() if d.metadata["Name"]}.items())})
            context = AuditContext(input_path, job["kind"], directory,
                                   request["profile"]["settings"], directory / "input.pdf" if request["pdf"] else None,
                                   request["render_word"],
                                   on_progress=lambda stage, detail: self.repository.progress(job_id, stage, detail),
                                   is_cancelled=lambda: bool(self.repository.get(job_id).get("cancel_requested")))
            checkpoint(context, "reading", "读取原稿")
            rendering = None
            if context.render_word and "legacy-school" not in request["profile"]["plugins"]:
                rendering = render_office(context)
                context.render_word = False
            result = execute(context, request["profile"], self.registry)
            if result.get("input_sha256") != request["input_sha256"]:
                invalidate_original(result, "integrity.snapshot_changed", "输入与建立任务时的快照不一致，请重新上传原稿", "输入快照")
            if rendering is not None:
                result["rendered_document"] = rendering
                if result.get("pdf_sha256") != rendering["pdf_sha256"]:
                    invalidate_original(result, "integrity.render_changed", "渲染 PDF 在检测期间变化，请重新检测", "渲染 PDF")
            result["filename"] = job["filename"]
            if request.get("scope_bindings") is not None:
                result["scope_bindings"] = request["scope_bindings"]
                result["source_profile_sha256"] = request["source_profile_sha256"]
            if request.get("repair"):
                result["repair"] = request["repair"]
                if sha256(directory / "repaired.docx") != request["input_sha256"]:
                    invalidate_original(result, "integrity.repaired_changed", "修复副本在检测期间已变化，请重新生成", "修复副本")
            original_path, original_pdf_path = self._original_sources.get(job_id, (None, None))
            if original_path is not None:
                path = original_path
                result["original_unchanged"] = path.is_file() and sha256(path) == request["input_sha256"]
                if not result["original_unchanged"]:
                    invalidate_original(result, "integrity.original_changed", "原文件在检测期间发生变化或已不可读，请重新检测", "原始 " + request.get("input_format", "docx").upper())
            if original_pdf_path is not None:
                path = original_pdf_path
                result["original_pdf_unchanged"] = path.is_file() and sha256(path) == request["pdf_sha256"]
                if not result["original_pdf_unchanged"]:
                    invalidate_original(result, "integrity.original_pdf_changed", "原始 PDF 在检测期间发生变化或已不可读，请重新检测", "原始 PDF")
            if request.get("revision_of_job_id"):
                result["revision_of_job_id"] = request["revision_of_job_id"]
            checkpoint(context, "reporting", "生成检测报告")
            write_json(directory / "report.json", result)
            render_reports(result, directory, job["filename"])
            write_json(directory / "artifacts-manifest.json", {p.relative_to(directory).as_posix(): sha256(p) for p in directory.rglob("*") if p.is_file() and p.name != "artifacts-manifest.json"})
            self.repository.seal_artifacts(job_id, sha256(directory / 'artifacts-manifest.json'))
            self.repository.finish(job_id, result, "检测引擎未完整运行，请查看问题明细和日志" if result["status"] == "incomplete" else None)
            if self.repository.get(job_id).get("cancel_requested"):
                self._finish_cancellation(job_id)
        except JobCancelled:
            self._finish_cancellation(job_id)
        except Exception as exc:
            import traceback
            # A report set is published only after all renderers and its seal
            # succeed. Keep failure evidence, never a partial final report.
            for name in FINAL_REPORT_FILES:
                try:
                    (directory / name).unlink(missing_ok=True)
                except OSError:
                    pass
            message = redact_local_paths(str(exc)) or "检测失败，请重新上传原稿"
            try:
                write_json(directory / "failure.json", {"error": message, "traceback": redact_local_paths(traceback.format_exc())})
            except OSError:
                pass  # A full/unwritable artifact disk cannot leave a claimed job running.
            self.repository.finish(job_id, error=message)
            if self.repository.metadata(job_id).get("cancel_requested"):
                self._finish_cancellation(job_id)
        finally:
            # The caller-owned path is needed only for this run's final
            # source-integrity comparison; do not retain it in the service.
            self._original_sources.pop(job_id, None)
        return self.get(job_id)

    @staticmethod
    def public(job):
        value = {k: v for k, v in job.items() if k not in {"request", "owner_pid"}}
        value["collection_id"] = (job.get("request") or {}).get("collection_id")
        value["input_format"] = (job.get("request") or {}).get("input_format", "docx")
        value["revision_of_job_id"] = (job.get("request") or {}).get("revision_of_job_id")
        value["batch_id"] = (job.get("request") or {}).get("batch_id")
        if (job.get("request") or {}).get("repair"):
            repair = job["request"]["repair"]
            value["repair"] = {key: repair[key] for key in (
                "source_job_id", "source_filename", "plan_id", "applied_count", "input_sha256", "output_sha256", "dropped_paired_pdf"
            ) if key in repair}
        return value

    def get(self, job_id):
        try:
            return self.public(self.repository.get(job_id))
        except ValueError:
            return self.public(self.repository.metadata(job_id))

    def page(self, limit=100, offset=0, query="", status=""):
        return self.repository.page(limit, offset, query, status)

    def cancel(self, job_id):
        return self.public(self.repository.request_cancel(job_id))

    def issue_evidence(self, job_id, index):
        from .evidence import issue_evidence
        return issue_evidence(self.jobs_dir / job_id, self.repository.get(job_id), index)

    def ocr_evidence(self, job_id, location):
        from .evidence import ocr_evidence
        return ocr_evidence(self.jobs_dir / job_id, self.repository.get(job_id), location)

    def comparison(self, job_id):
        from .comparison import compare_jobs
        current = self.repository.get(job_id)
        parent_id = current['request'].get('revision_of_job_id') or (current['request'].get('repair') or {}).get('source_job_id')
        if not parent_id:
            return {'available': False, 'reason': '此任务没有关联的原检测',
                    'groups': {key: [] for key in ('resolved', 'remaining', 'new', 'incomparable')},
                    'summary': {key: 0 for key in ('resolved', 'remaining', 'new', 'incomparable')}}
        return compare_jobs(self.repository.get(parent_id), current, self.jobs_dir / parent_id, self.jobs_dir / job_id)

    def job_reviews(self, job_id, payload=None):
        from .evidence import validate_snapshot
        job = self.repository.get(job_id)
        validate_snapshot(job, self.jobs_dir / job_id)
        return self.reviews.get(job) if payload is None else self.reviews.save(job, payload)

    def batch(self, batch_id):
        from .batches import get_batch
        return get_batch(self, batch_id)

    def create_batch(self, documents, **options):
        from .batches import create_batch
        return create_batch(self, documents, **options)

    def batch_write_guard(self) -> AbstractContextManager[None]:
        """Serialize batch receipt writes across threads and processes."""
        root = self.data_dir / "batches"
        root.mkdir(exist_ok=True)
        return write_lock(root, self._batch_lock)

    def _finish_cancellation(self, job_id):
        self.repository.complete_cancel(job_id)
        directory = self.jobs_dir / job_id
        # Partial engine evidence remains available; a cancelled run has no report.
        for name in FINAL_REPORT_FILES:
            (directory / name).unlink(missing_ok=True)
        write_json(directory / "cancelled.json", {"job_id": job_id, "status": "cancelled",
                   "reason": "已在当前步骤结束后取消；保留输入与已提取证据，未形成检测结论"})

    def retry(self, job_id):
        old = self.repository.get(job_id)
        if old["status"] in {"queued", "running"}:
            raise ValueError("任务正在排队或运行，请等待完成")
        request = old["request"]
        directory = self.jobs_dir / old["id"]
        input_path = directory / ("input." + request.get("input_format", "docx"))
        document = _retry_snapshot(input_path, request["input_sha256"], "历史输入快照不可读或哈希不符，不能重试")
        pdf = _retry_snapshot(directory / "input.pdf", request["pdf_sha256"],
                              "历史PDF快照不可读或哈希不符，不能重试") if request["pdf"] else None
        repair = {key: value for key, value in request.get("repair", {}).items() if key != "operation_key"} or None
        if repair is not None:
            repair["retry_of_job_id"] = job_id
        return self.create(document, old["filename"], kind=old["kind"], pdf=pdf,
                           render_word=request["render_word"], profile_snapshot=request.get("source_profile", request["profile"]),
                           scope_bindings=request.get("scope_bindings"),
                           collection_id=request.get("collection_id"), repair=repair,
                           revision_of_job_id=request.get("revision_of_job_id"))

    def repair_plan(self, job_id):
        from .evidence import validate_snapshot
        job = self.repository.get(job_id)
        request = job["request"]
        result = job.get("result") or {}
        unavailable = {"job_id": job_id, "input_sha256": request.get("input_sha256", ""),
                       "available": False, "plan_id": "", "candidates": [], "skipped": []}
        if job["status"] != "completed" or not result or result.get("status") == "incomplete":
            return {**unavailable, "reason": "请先完成检测，再查看可修复项。"}
        if request.get("input_format", "docx") != "docx":
            return {**unavailable, "reason": "针对性格式修复目前仅支持 DOCX。"}
        directory = self.jobs_dir / job_id
        path = safe_child(directory, "input.docx")
        result = validate_snapshot(job, directory)
        profile = request["profile"]
        plan = build_repair_plan(path, result, profile)
        validate_snapshot(job, directory)
        return {**plan, "job_id": job_id}

    def repair(self, job_id, plan_id, selected_ids):
        from .evidence import validate_snapshot
        if not isinstance(plan_id, str) or not plan_id:
            raise ValueError("请先读取修复预览")
        if (not isinstance(selected_ids, list) or not selected_ids or len(selected_ids) > 1000
                or any(not isinstance(value, str) or not value or len(value) > 128 for value in selected_ids)
                or len(set(selected_ids)) != len(selected_ids)):
            raise ValueError("请选择有效且不重复的修复项")
        # A process-shared guard makes a retried POST return its existing job.
        with write_lock(self.jobs_dir, self._repair_lock):
            plan = self.repair_plan(job_id)
            if not plan.get("available"):
                raise ValueError(plan.get("reason", "当前任务没有可修复项"))
            if plan["plan_id"] != plan_id:
                raise ValueError("修复预览已过期，请重新读取")
            candidates = plan.get("candidates")
            if not isinstance(candidates, list):
                raise ValueError("修复预览结构无效，请重新读取")
            candidate_ids = {
                item.get("id")
                for item in candidates
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if set(selected_ids) - candidate_ids:
                raise ValueError("修复选项无效，请重新读取预览")
            key = hashlib.sha256(json.dumps([job_id, plan_id, sorted(selected_ids)],
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
            existing = self.repository.repair_job(key)
            if existing is not None:
                return self.public(existing)
            old = self.repository.get(job_id)
            request = old["request"]
            path = safe_child(self.jobs_dir / job_id, "input.docx")
            document, receipt = apply_repair_plan(path, plan, selected_ids)
            validate_snapshot(old, self.jobs_dir / job_id)
            receipt.update(source_job_id=job_id, source_filename=old["filename"], operation_key=key, selected_ids=sorted(selected_ids),
                           applied_count=len(receipt["changes"]), dropped_paired_pdf=bool(request.get("pdf")))
            stem = Path(old["filename"]).stem
            filename = (stem if stem.endswith("-修复") else stem + "-修复") + ".docx"
            bindings = json.loads(json.dumps(request.get("scope_bindings")))
            if bindings is not None:
                source_scope_digest = document_scope_digest(path)
                with self.document_previews.temporary_document(document, filename) as repaired_path:
                    repaired_scope_digest = document_scope_digest(repaired_path)
                if source_scope_digest != repaired_scope_digest:
                    raise ValueError("修复副本的内容、样式归属或分节发生变化，请重新确认原稿范围")
                bindings["input_sha256"] = hashlib.sha256(document).hexdigest()
                receipt["scope_revalidation"] = {"source_input_sha256": request["input_sha256"],
                    "input_sha256": bindings["input_sha256"], "method": "revalidated_unchanged_styles_and_sections",
                    "source_scope_sha256": source_scope_digest, "scope_sha256": repaired_scope_digest}
            return self.create(document, filename, kind=old["kind"], profile_snapshot=request.get("source_profile", request["profile"]),
                               scope_bindings=bindings,
                               collection_id=request.get("collection_id"), repair=receipt)

    def artifacts(self, job_id):
        job = self.repository.get(job_id)
        from urllib.parse import quote
        directory = self.jobs_dir / job_id
        integrity = 'sealed' if job.get('artifacts_manifest_sha256') else 'unverified'
        return [{"name": p.name, "path": p.relative_to(directory).as_posix(), "size": p.stat().st_size, "integrity": integrity,
                 "url": f"/api/jobs/{job_id}/artifacts/" + quote(p.relative_to(directory).as_posix())}
                for p in sorted(directory.rglob("*")) if p.is_file() and not p.is_symlink() and not p.name.startswith(".writing-")
                and not ((job.get('result') is None or job.get('cancel_requested')) and p.name in FINAL_REPORT_FILES)]

    def artifact(self, job_id, relative):
        path, _ = self.artifact_bytes(job_id, relative)
        return path

    def _artifact_manifest(self, job):
        directory = self.jobs_dir / job['id']
        manifest_path = directory / 'artifacts-manifest.json'
        expected = job.get('artifacts_manifest_sha256')
        required = bool(expected) or ((job.get('request') or {}).get('artifacts_manifest_version') == 1 and job.get('result') is not None)
        if not manifest_path.is_file():
            if required:
                raise ValueError('附件完整性清单缺失，请重新生成报告')
            return None, None
        try:
            raw = manifest_path.read_bytes()
            if required and (not expected or hashlib.sha256(raw).hexdigest() != expected):
                raise ValueError('附件完整性清单校验失败，请重新生成报告')
            manifest = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError('附件完整性清单不可读取，请重新生成报告') from exc
        if not isinstance(manifest, dict) or any(not isinstance(k, str) or not isinstance(v, str) or len(v) != 64
                                                for k, v in manifest.items()):
            raise ValueError('附件完整性清单格式无效，请重新生成报告')
        return manifest, raw

    def _artifact_bytes(self, job, relative, manifest, manifest_raw):
        directory = self.jobs_dir / job['id']
        path = safe_child(directory, relative)
        if (job.get('result') is None or job.get('cancel_requested')) and path.name in FINAL_REPORT_FILES:
            raise KeyError('任务没有完整检测报告')
        if not path.is_file() or path.is_symlink():
            raise KeyError('文件不存在')
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError('附件无法读取，请重新生成报告') from exc
        if path == directory / 'artifacts-manifest.json':
            if raw != manifest_raw:
                raise ValueError('附件完整性清单已变化，请重新生成报告')
        elif manifest is not None:
            key = path.relative_to(directory).as_posix()
            expected = manifest.get(key, manifest.get(str(path.relative_to(directory))))
            if not expected or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('附件完整性校验失败，请重新生成报告')
        return path, raw

    def artifact_bytes(self, job_id, relative):
        """Return the same bytes that passed verification for delivery."""
        job = self.repository.get(job_id)
        manifest, raw = self._artifact_manifest(job)
        return self._artifact_bytes(job, relative, manifest, raw)

    def export(self, job_id, output):
        job = self.repository.get(job_id)
        if job['status'] == 'cancelled' or job.get('cancel_requested'):
            raise ValueError('已取消任务没有完整报告可导出，请从任务附件读取原稿或执行证据')
        output = Path(output).resolve()
        source = (self.jobs_dir / job_id).resolve()
        manifest, manifest_raw = self._artifact_manifest(job)
        if output == source:
            present = set()
            for file in source.rglob('*'):
                if file.is_file():
                    relative = file.relative_to(source).as_posix()
                    self._artifact_bytes(job, relative, manifest, manifest_raw)
                    present.add(relative)
            if manifest is not None and ({key.replace('\\', '/') for key in manifest} - present):
                raise ValueError('报告附件缺失，不能导出')
            if self._artifact_manifest(self.repository.get(job_id))[1] != manifest_raw:
                raise ValueError('导出期间附件清单已变化')
            return source
        if output.is_relative_to(self.jobs_dir.resolve()):
            raise ValueError("导出目录不能位于任务存储目录内")
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("导出目录不能包含任务源目录或位于任务内部")
        if output.exists() and not output.is_dir():
            raise ValueError("导出路径必须是目录")
        if output.exists() and any(output.iterdir()):
            raise ValueError("导出目录不是空目录；请指定新的目录，避免覆盖已有报告")
        output.parent.mkdir(parents=True, exist_ok=True)
        staged = output.parent / ('.formatly-export-' + uuid.uuid4().hex)
        staged.mkdir()
        try:
            copied = set()
            for file in source.rglob('*'):
                if file.is_symlink():
                    raise ValueError('报告目录包含链接，不能导出')
                if file.is_file():
                    relative = file.relative_to(source).as_posix()
                    _, data = self._artifact_bytes(job, relative, manifest, manifest_raw)
                    atomic_write(safe_child(staged, relative), data)
                    copied.add(relative)
            if manifest is not None and ({key.replace('\\', '/') for key in manifest} - copied):
                raise ValueError('报告附件缺失，不能导出')
            if not job.get('artifacts_manifest_sha256'):
                write_json(staged / 'export-integrity.json', {'status': 'unverified',
                           'reason': '此任务没有持久化的产物清单摘要，不能证明附件完整性'})
            # Recheck the seal after reading all files; published files contain
            # only the already verified bytes, never a second source read.
            if self._artifact_manifest(self.repository.get(job_id))[1] != manifest_raw:
                raise ValueError('导出期间附件清单已变化')
            if output.exists():
                output.rmdir()  # Fails safely if another writer filled it.
            staged.rename(output)
        finally:
            if staged.is_dir():
                shutil.rmtree(staged)
        return output

    def doctor(self) -> dict[str, Any]:
        import platform
        checks = [{"name": "Python", "status": "ok", "message": platform.python_version()},
                  {"name": "任务数据库", "status": "ok", "message": "本地任务数据库可用"},
                  {"name": "数据目录", "status": "ok", "message": "本地数据目录可用"}]
        capabilities = self.capabilities()
        for key, name in (("pdf", "PDF 文本与页面解析"), ("ocr", "本地中英文 OCR")):
            capability = capabilities[key]
            checks.append({"name": name, "status": "ok" if capability["available"] else "optional", "message": capability["reason"]})
        for error in self.profiles.list_errors():
            checks.append({"name": f"规则方案 · {error['file']}", "status": "warning", "message": error["message"]})
        for plugin in self.registry.list():
            checks.append({"id": plugin["id"], "name": plugin["name"],
                           "status": "ok" if plugin["available"] else "optional", "message": plugin["reason"]})
        result: dict[str, Any] = {"status": "ready" if all(c["status"] == "ok" for c in checks) else "degraded", "checks": checks}
        try:
            external = self.registry.get("legacy-school")
        except ValueError:
            external = None
        diagnostics = getattr(external, "diagnostics", None)
        if callable(diagnostics):
            from ..adapters.legacy import public_engine_info
            try:
                diagnostic_value = diagnostics()
            except (OSError, RuntimeError, ValueError, TypeError, AttributeError, LookupError):
                diagnostic_value = None
            if isinstance(diagnostic_value, dict):
                result["external_engine"] = public_engine_info(diagnostic_value)
        return result


