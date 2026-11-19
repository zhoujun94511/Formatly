"""Optional, bounded local Word/WPS export of an immutable DOCX snapshot."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import posixpath
import re
import sys
import time
import math
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from zipfile import ZipFile

from ..domain import AuditContext
from ..files import MAX_FILE_BYTES, W, atomic_write, read_docx, sha256, write_json
from .processes import managed_python_worker
from .runtime import pdf_working_directory

PROGIDS = ("Word.Application", "KWPS.Application")


def _validate_instruction(instruction: str) -> None:
    words = instruction.strip().upper().split()
    if words and words[0] in {"DDE", "DDEAUTO", "INCLUDETEXT", "INCLUDEPICTURE", "DATABASE", "LINK"}:
        raise ValueError("文档包含外部数据域；请移除后导出，或自行提供配对 PDF")
    if words and words[0] == "HYPERLINK" and not re.fullmatch(
            r'\s*HYPERLINK\s+\\l\s+(?:"[^"\\]{1,200}"|[A-Za-z0-9_]{1,200})\s*', instruction, re.I):
        raise ValueError("文档包含外部或无法确定的链接域；请移除后导出，或自行提供配对 PDF")


def _validate_fields(root: ElementTree.Element) -> None:
    stack: list[list[str]] = []
    for node in root.iter():
        if node.tag == W + "altChunk":
            raise ValueError("文档包含待导入的外部内容，不能交给本机应用导出")
        if node.tag == W + "fldSimple":
            _validate_instruction(node.get(W + "instr", ""))
        elif node.tag == W + "fldChar":
            boundary = node.get(W + "fldCharType")
            if boundary == "begin":
                stack.append([])
            elif boundary == "end" and stack:
                _validate_instruction("".join(stack.pop()))
            elif boundary != "separate" or not stack:
                raise ValueError("文档域结构不完整，请在 Word/WPS 中处理后提供配对 PDF")
        elif node.tag == W + "instrText" and node.text:
            if not stack:
                raise ValueError("文档包含未绑定的域指令，不能交给本机应用导出")
            stack[-1].append(node.text)
    if stack:
        raise ValueError("文档域结构不完整，请在 Word/WPS 中处理后提供配对 PDF")


def probe_office() -> dict:
    """Read registration only; never launch an office application to probe."""
    result = {"available": False, "renderers": [], "reason": "本地 Word/WPS 导出仅支持 Windows"}
    if os.name != "nt":
        return result
    if importlib.util.find_spec("pythoncom") is None or importlib.util.find_spec("win32com") is None:
        result["reason"] = "需在 Windows 的服务解释器安装 pywin32，并安装 Word 或 WPS"
        return result
    winreg = importlib.import_module("winreg")
    renderers = []
    for progid in PROGIDS:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID", 0, winreg.KEY_READ | view) as key:
                    clsid = winreg.QueryValue(key, None)
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + "\\LocalServer32", 0, winreg.KEY_READ | view):
                    renderers.append(progid)
                    break
            except OSError:
                continue
    return {"available": bool(renderers), "renderers": renderers,
            "reason": "可使用本机 Word/WPS 只读导出 PDF；实际应用与版本以导出记录为准" if renderers else "未发现已注册的 Word/WPS 本地导出接口"}


def validate_office_input(path: Path) -> None:
    """Refuse active and linked content before handing bytes to native apps."""
    package = read_docx(path)
    with ZipFile(path) as archive:
        for name in package["parts"]:
            lowered = name.lower()
            if ("vbaproject" in lowered or lowered.startswith(("word/embeddings/", "customui/"))
                    or lowered.endswith((".bin", ".exe", ".dll"))):
                raise ValueError("文档包含宏、嵌入对象或活动内容；请移除后导出，或自行提供配对 PDF")
            if not lowered.endswith((".rels", ".xml")):
                continue
            raw = archive.read(name)
            declarations = raw.replace(b"\x00", b"").upper()
            if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                raise ValueError("文档包含不支持的 XML 声明，不能交给本地应用导出")
            try:
                root = ElementTree.fromstring(raw)
            except ElementTree.ParseError as exc:
                raise ValueError("文档包含无效 XML，不能交给本地应用导出") from exc
            for node in root.iter():
                content_type = node.get("ContentType", "").lower()
                relationship = node.get("Type", "").lower()
                if (any(token in content_type for token in ("vba", "macroenabled", "activex", "oleobject"))
                        or relationship.rsplit("/", 1)[-1] in {"vbaproject", "oleobject", "package", "control", "activexcontrol", "afchunk"}):
                    raise ValueError("文档包含活动部件关系，不能交给本机应用导出")
                if lowered.endswith(".rels") and node.tag.endswith("}Relationship"):
                    target = unquote(node.get("Target", "")).replace("\\", "/")
                    uri = urlsplit(target)
                    if node.get("TargetMode", "Internal").lower() != "internal" or uri.scheme or uri.netloc:
                        raise ValueError("文档包含外部链接；请移除后导出，或自行提供配对 PDF")
                    base = posixpath.dirname(posixpath.dirname(name))
                    part = posixpath.normpath(uri.path.lstrip("/") if uri.path.startswith("/") else posixpath.join(base, uri.path))
                    if part.startswith("../") or part not in package["parts"]:
                        raise ValueError("文档包关系缺失或越界，请自行提供配对 PDF")
            _validate_fields(root)


def render_office(context: AuditContext, *, timeout: float = 90) -> dict:
    """Export in an owned worker and keep only verified output and provenance."""
    from ..application.job_control import checkpoint

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("本地导出超时须为不超过300秒的有限正数")
    validate_office_input(context.input_path)
    capability = probe_office()
    if not capability["available"]:
        raise ValueError(capability["reason"])
    digest = sha256(context.input_path)
    with pdf_working_directory(context.output_dir) as temporary:
        source, output, status = temporary / "source.docx", temporary / "render.pdf", temporary / "status.json"
        atomic_write(source, context.input_path.read_bytes())
        if sha256(source) != digest:
            raise ValueError("渲染输入副本校验失败")
        command = [sys.executable, "-B", "-m", "formatly.documents.office_worker", str(source), str(output), str(status), capability["renderers"][0]]
        deadline = time.monotonic() + timeout
        with managed_python_worker(command, cwd=Path(__file__).resolve().parents[2]) as process:
            while process.poll() is None:
                checkpoint(context, "reading", "使用本机 Word/WPS 只读导出 PDF")
                if time.monotonic() >= deadline:
                    raise ValueError("本地 Word/WPS 导出超时，请关闭应用提示窗口或自行提供配对 PDF")
                time.sleep(.2)
        if not status.is_file() or status.stat().st_size > 16384:
            raise ValueError("本地 Word/WPS 导出未产生有效记录")
        receipt = json.loads(status.read_text(encoding="utf-8"))
        if process.returncode or receipt.get("status") != "completed":
            write_json(context.output_dir / "render-error.json", receipt)
            raise ValueError(receipt.get("message", "本地 Word/WPS 导出失败，请自行提供配对 PDF"))
        if (sha256(context.input_path) != digest or sha256(source) != digest
                or not output.is_file() or not 0 < output.stat().st_size <= MAX_FILE_BYTES):
            raise ValueError("渲染输入变化或输出超限，不能使用此 PDF")
        data = output.read_bytes()
        if not data.startswith(b"%PDF-") or len(data) > MAX_FILE_BYTES:
            raise ValueError("本地应用未导出有效 PDF")
        target = context.output_dir / "rendered" / "document.pdf"
        atomic_write(target, data)
        context.pdf_path = target
        return {"path": "rendered/document.pdf", "input_sha256": digest, "pdf_sha256": sha256(target),
                "renderer": str(receipt.get("renderer", ""))[:120], "version": str(receipt.get("version", ""))[:60],
                "executable": str(receipt.get("executable", ""))[:120],
                "progid": capability["renderers"][0], "read_only": True}
