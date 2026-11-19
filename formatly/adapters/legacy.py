"""Run school-specific document checks in an isolated Python interpreter.

The configured rules include author cover information and school platform
requirements. Use this adapter only for documents within that declared scope.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from ..privacy import redact_local_paths
from .engine_config import load_engine_config
from .engine_validation import (REQUIRED_FILES, runtime_probe_script, validate_entrypoints,
                                validate_sources, validate_vendor)


TIMEOUT_SECONDS = 600


@contextmanager
def _word_render_lock():
    """Share one nonblocking COM render lock across all CLI/service processes.

    The lock file remains in place after release: removing it can let another
    process lock a new file while an earlier waiter still holds the old one.
    The operating system releases the lock if a process crashes.
    """
    path = Path(tempfile.gettempdir()) / "Formatly-word-render.lock"
    try:
        stream = path.open("a+b")
    except OSError as exc:
        raise RuntimeError("无法创建排版应用互斥锁，请检查临时目录权限") from exc
    acquired = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise RuntimeError("排版应用正被另一个 Formatly 检测任务占用，请待其完成后重试") from exc
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _legacy_root() -> Path:
    configured = os.environ.get("FORMATLY_LEGACY_ROOT")
    return (Path(configured).expanduser() if configured else
            Path(__file__).resolve().parents[3] / "graduation-format-audit").resolve()


_CHECKS = {
    "configuration": ("本机配置", "配置已读取", "本机集成配置无效，请在运行主机修复或重新配置"),
    "files": ("引擎文件", "必需脚本与配置齐全", "必需脚本或配置缺失"),
    "python": ("Python 解释器", "已找到 Python 文件", "Python 不存在或不能启动，请核对 FORMATLY_LEGACY_PYTHON"),
    "dependencies": ("Python 依赖", "所需依赖可导入", "所需依赖缺失或不能导入，请在引擎 Python 环境安装依赖"),
    "sources": ("规则依据", "规则依据文件与 SHA256 一致", "规则依据清单无效、原件缺失或 SHA256 不一致"),
    "vendor": ("vendor 版本", "vendor 文件与版本清单一致", "vendor 版本清单无效、文件缺失或 SHA256 不一致"),
    "entrypoints": ("调用入口", "入口函数签名符合适配器调用", "scripts/run_audit.py 的入口或函数签名不符合适配器调用"),
    "yaml": ("格式规则", "两类 YAML 格式规则结构有效", "configs/thesis.yaml 或 configs/intern.yaml 的格式规则结构无效"),
}


def public_engine_info(probe: dict) -> dict:
    """Return only fixed public fields, never host paths or manifest contents."""
    value = probe.get("public", probe)
    if not isinstance(value, dict):
        value = {}
    stage = value.get("stage", "error")
    discovery = value.get("discovery", "default")
    if not isinstance(stage, str):
        stage = "error"
    if not isinstance(discovery, str):
        discovery = "default"
    checks = []
    supplied_checks = value.get("checks", [])
    for item in supplied_checks if isinstance(supplied_checks, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] not in _CHECKS:
            continue
        check_id = item["id"]
        status = item.get("status")
        status = status if isinstance(status, str) and status in {"ok", "error", "pending"} else "pending"
        label, success, failure = _CHECKS[check_id]
        checks.append({"id": check_id, "label": label, "status": status,
                       "message": success if status == "ok" else failure if status == "error" else "待前置检查通过"})
    supplied_files = value.get("required_files", [])
    required = {item["path"]: item.get("present") is True
                for item in (supplied_files if isinstance(supplied_files, list) else [])
                if isinstance(item, dict) and isinstance(item.get("path"), str)}
    return {
        "plugin_id": "legacy-school", "profile_id": "school-specific",
        "available": value.get("available") is True and stage == "ready",
        "stage": stage if stage in {"missing", "files", "python", "dependencies", "rules", "ready", "error"} else "error",
        "discovery": discovery if discovery in {"default", "environment", "configuration"} else "default",
        "root_configured": value.get("root_configured") is True,
        "python_configured": value.get("python_configured") is True,
        "kinds": ["thesis", "intern"], "formats": ["docx"], "checks": checks,
        "required_files": [{"path": name, "present": required.get(name, False)} for name in REQUIRED_FILES],
    }


def resolve_engine_settings(data_dir, root=None, python=None) -> tuple[Path, Path, dict]:
    environment_root = (os.environ.get("FORMATLY_LEGACY_ROOT") or None) if root is None else None
    environment_python = (os.environ.get("FORMATLY_LEGACY_PYTHON") or None) if python is None else None
    override_root = root if root is not None else environment_root
    # An explicit new engine root must not inherit an unrelated saved interpreter.
    config = {}
    if override_root is None or (python is None and environment_python is None):
        try:
            config = load_engine_config(data_dir)
        except ValueError:
            if override_root is None:
                raise
    selected_root = Path(override_root or config.get("root") or _legacy_root()).expanduser().resolve()
    saved_python = config.get("python") if config.get("root") == str(selected_root) else None
    configured_python = python if python is not None else environment_python or saved_python
    candidates = ([Path(configured_python).expanduser()] if configured_python else [
        selected_root / ".venv" / "Scripts" / "python.exe",
        selected_root / ".venv" / "bin" / "python", Path(sys.executable),
    ])
    interpreter = next((path.resolve() for path in candidates if path.is_file()), candidates[0].resolve())
    discovery = ("environment" if environment_root or environment_python else
                 "configuration" if root is not None or python is not None or config else "default")
    return selected_root, interpreter, {
        "discovery": discovery, "root_configured": bool(override_root or config.get("root")),
        "python_configured": bool(configured_python),
    }


def probe_legacy(data_dir=None, *, root: Path | None = None, python: Path | None = None) -> dict:
    """Validate a trusted host-local engine without importing its implementation."""
    public: dict[str, Any] = {"available": False, "stage": "error", "discovery": "default",
              "root_configured": False, "python_configured": False,
              "checks": [{"id": name, "status": "pending"} for name in _CHECKS], "required_files": []}
    result: dict[str, Any] = {"available": False, "reason": "", "root": "", "python": "",
              "scope": "仅适用于配置的学校与材料范围，不能作为通用校规"}

    def check(identifier: str, ok: bool) -> None:
        next(item for item in public["checks"] if item["id"] == identifier)["status"] = "ok" if ok else "error"

    def finish(stage: str, reason: str) -> dict:
        public.update(stage=stage, available=stage == "ready")
        result.update(available=public["available"], reason=reason, public=public_engine_info(public))
        return result

    unaffected = "不影响学校要求上传、预置方案与自建方案。"
    try:
        selected_root, interpreter, settings = resolve_engine_settings(data_dir, root, python)
    except (OSError, RuntimeError, ValueError):
        check("configuration", False)
        return finish("error", "可选外部专项引擎的本机配置无效；请在运行主机修复 integrations.json。" + unaffected)
    result.update(root=str(selected_root), python=str(interpreter))
    public.update(settings)
    check("configuration", True)
    try:
        public["required_files"] = [{"path": name, "present": (selected_root / name).is_file()}
                                    for name in REQUIRED_FILES]
        missing = [item["path"] for item in public["required_files"] if not item["present"]]
        check("files", not missing)
        if missing:
            return finish("files" if selected_root.is_dir() else "missing",
                "可选外部专项引擎未安装或不完整；" + unaffected + " 缺少：" + ", ".join(missing))
        check("python", interpreter.is_file())
        if not interpreter.is_file():
            return finish("python", "可选外部专项引擎 Python 未找到；请配置 FORMATLY_LEGACY_PYTHON。" + unaffected)
        try:
            process = subprocess.run(
                [str(interpreter), "-I", "-B", "-c", runtime_probe_script(), str(selected_root)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
            )
        except (OSError, subprocess.SubprocessError):
            check("python", False)
            return finish("python", "可选外部专项引擎 Python 无法启动或检查超时。" + unaffected)
        try:
            runtime = json.loads(process.stdout) if process.returncode == 0 else {}
        except (ValueError, TypeError):
            runtime = {}
        dependencies = isinstance(runtime, dict) and runtime.get("dependencies") is True
        check("dependencies", dependencies)
        if not dependencies:
            return finish("dependencies", "可选外部专项引擎 Python 依赖不完整或检查失败；请在运行主机安装所需依赖。" + unaffected)
        for check_id, validator in (("sources", validate_sources), ("vendor", validate_vendor),
                                    ("entrypoints", validate_entrypoints)):
            try:
                validator(selected_root)
            except (OSError, UnicodeError, ValueError, TypeError, KeyError, SyntaxError, RecursionError):
                check(check_id, False)
                return finish("rules", "可选外部专项引擎未就绪：" + _CHECKS[check_id][2] + "。" + unaffected)
            check(check_id, True)
        yaml_valid = runtime.get("rules") is True
        check("yaml", yaml_valid)
        if not yaml_valid:
            return finish("rules", "可选外部专项引擎未就绪：" + _CHECKS["yaml"][2] + "。" + unaffected)
    except (OSError, RuntimeError, ValueError):
        return finish("error", "可选外部专项引擎检查失败；请在运行主机核对配置和文件权限。" + unaffected)
    return finish("ready", "专项引擎文件、Python、依赖、规则依据及版本校验通过；文档检测与版式渲染能力以实际执行为准")


def _stop_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=15, check=False)
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=15)


def redact_process_log(path: Path, *values: Path | None) -> None:
    """Remove local filesystem identities from the child-process log."""
    try:
        content = redact_local_paths(path.read_text(encoding='utf-8', errors='replace'), *values)
        path.write_text(content, encoding='utf-8')
    except OSError:
        # Never publish a raw log when sanitizing it could not be completed.
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError("专项诊断日志无法清理，请检查任务目录权限后重试") from exc


def run_legacy(input_path: Path, kind: str, output_dir: Path,
               pdf_path: Path | None = None, render_word: bool = False, *, data_dir=None,
               root: Path | None = None, python: Path | None = None) -> dict:
    """Audit exactly one explicit document and retain all evidence in legacy/."""
    if kind not in {"thesis", "intern"}:
        raise ValueError("kind 必须为 thesis 或 intern")
    source = Path(input_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise ValueError("专项检测需要存在的 DOCX 文件")
    pdf = Path(pdf_path).resolve() if pdf_path is not None else None
    if pdf is not None and (not pdf.is_file() or pdf.suffix.lower() != ".pdf"):
        raise ValueError("PDF 配对文件不存在或扩展名不正确")
    probe = (probe_legacy(data_dir=data_dir, root=root, python=python)
             if data_dir is not None or root is not None or python is not None else probe_legacy())
    if not probe["available"]:
        raise RuntimeError(probe["reason"])
    destination = Path(output_dir).resolve() / "legacy"
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RuntimeError("专项证据目录必须为空，避免覆盖已有检测证据")
    command = [probe["python"], "-I", "-B", str(Path(__file__).with_name("legacy_worker.py")),
               "--input", str(source), "--kind", kind, "--output", str(destination)]
    if pdf is not None:
        command.extend(["--pdf", str(pdf)])
    if render_word:
        command.append("--render-word")
    environment = {**os.environ, "FORMATLY_LEGACY_ROOT": probe["root"],
                   "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        with (_word_render_lock() if render_word else nullcontext()):
            with (destination / "process.log").open("wb") as log:
                try:
                    process = subprocess.Popen(command, cwd=probe["root"], env=environment,
                                               stdout=log, stderr=subprocess.STDOUT,
                                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                                               start_new_session=os.name != "nt")
                    try:
                        returncode = process.wait(timeout=TIMEOUT_SECONDS)
                    except subprocess.TimeoutExpired:
                        _stop_process_tree(process)
                        raise RuntimeError(f"专项检测超过 {TIMEOUT_SECONDS} 秒，已停止；诊断见专项 process.log")
                except OSError as exc:
                    raise RuntimeError("无法启动专项检测进程：" + redact_local_paths(str(exc))) from exc
    finally:
        redact_process_log(destination / "process.log", source, pdf, destination,
                            Path(probe["root"]), Path(probe["python"]))
    report_path = destination / "report.json"
    if returncode != 0:
        error_path = destination / "worker_error.json"
        detail = ""
        if error_path.is_file():
            try:
                detail = json.loads(error_path.read_text(encoding="utf-8")).get("message", "")
            except (ValueError, OSError):
                pass
        raise RuntimeError(f"专项检测未完整执行（退出码 {returncode}）：" + redact_local_paths(detail))
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("专项检测未输出有效 report.json") from exc
    if report.get("kind") != kind or report.get("original_unchanged") is not True:
        raise RuntimeError("专项检测返回的文档类型或原件完整性证据无效")
    return report


