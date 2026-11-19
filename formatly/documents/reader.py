"""One bounded text/evidence reader for original documents and school sources.

DOCX XML remains available to the existing formatting plugins. Other formats
are never converted to DOCX: absent formatting properties must remain absent.
PDF parsing and native rendering run in an isolated, time-limited process.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..files import MAX_FILE_BYTES, NS, read_docx
from ..privacy import public_ocr_information
from .processes import managed_python_worker
from .runtime import hidden_process_options, pdf_working_directory

FORMATS = {".docx": "docx", ".pdf": "pdf", ".txt": "txt", ".md": "md", ".json": "json"}
MAX_TEXT_BYTES = 1024 * 1024
MAX_PDF_PAGES = 300
MAX_OCR_PAGES = 20
PDF_TIMEOUT_SECONDS = 150
MAX_WORKER_BYTES = 24 * 1024 * 1024


def document_format(path_or_filename) -> str:
    extension = Path(path_or_filename).suffix.lower()
    if extension not in FORMATS:
        raise ValueError("仅支持 DOCX、PDF、TXT、MD、JSON；.doc 文档请先另存为 DOCX")
    return FORMATS[extension]


def probe_pdf() -> tuple[bool, str]:
    available = all(importlib.util.find_spec(name) is not None for name in ("pdfplumber", "pypdfium2"))
    return available, ("本地 PDF 文本、字符属性与页面解析可用" if available else
                       "缺少 PDF 解析依赖，请安装当前 Formatly 的 Python 依赖（pdfplumber、pypdfium2）")


def probe_ocr() -> dict[str, Any]:
    """Discover an installed local OCR engine; never download executables/models."""
    configured = os.environ.get("FORMATLY_TESSERACT", "").strip()
    executable = str(Path(configured).expanduser()) if configured else shutil.which("tesseract")
    base: dict[str, Any] = {"available": False, "reason": "未发现本地 Tesseract；扫描页需安装 OCR 及中文语言数据，或提供人工核对的转录文本",
            "languages": [], "selected_languages": [], "executable": executable}
    if not executable or not Path(executable).is_file():
        return base
    try:
        process = subprocess.run([executable, "--list-langs"], capture_output=True, timeout=5,
                                 text=True, encoding="utf-8", errors="replace", **hidden_process_options())
        if process.returncode:
            return {**base, "reason": "Tesseract 语言数据探测失败，请检查 FORMATLY_TESSERACT 与本地 tessdata"}
        languages = sorted({line.strip() for line in (process.stdout + "\n" + process.stderr).splitlines()
                            if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_/-]*", line.strip())})
        requested = os.environ.get("FORMATLY_OCR_LANGS", "").strip()
        # The Chinese model also recognizes Latin text/digits. Adding the
        # English model by default can replace clear Chinese form labels with
        # Latin lookalikes (e.g. 姓名 -> WEA). Prefer Chinese when installed;
        # explicit FORMATLY_OCR_LANGS can select another local language set.
        selected = requested.split("+") if requested else (["chi_sim"] if "chi_sim" in languages else ["eng"] if "eng" in languages else [])
        if not selected or any(not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_/-]*", lang) or lang not in languages for lang in selected):
            return {**base, "languages": languages, "reason": "本地 OCR 缺少所需语言数据；请检查 FORMATLY_OCR_LANGS 与 tessdata"}
        reason = "本地 Tesseract OCR 可用（" + "+".join(selected) + "）；识别文字仍须复核"
        if "chi_sim" not in selected:
            reason += "；未启用简体中文语言数据，中文材料可能无法正确识别"
        return {**base, "available": True, "reason": reason, "languages": languages, "selected_languages": selected}
    except (OSError, subprocess.TimeoutExpired):
        return {**base, "reason": "本地 Tesseract 无法启动或探测超时，请检查 OCR 环境"}


def _read_text(path: Path) -> tuple[str, str, list[str]]:
    raw = path.read_bytes()
    warnings = []
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text, encoding = raw.decode("utf-16"), "utf-16"
        else:
            try:
                text, encoding = raw.decode("utf-8-sig"), "utf-8"
            except UnicodeError:
                text, encoding = raw.decode("gb18030"), "gb18030"
                warnings.append("文本按 GB18030 编码读取；请核对文字是否正确，建议保存为 UTF-8")
    except UnicodeError as exc:
        raise ValueError("文本编码不可读，请保存为 UTF-8、带 BOM 的 UTF-16 或 GB18030") from exc
    if "\x00" in text or any(ord(char) < 32 and char not in "\t\n\r\f" for char in text):
        raise ValueError("文本含二进制或不支持的控制字符，请提供有效的纯文本文件")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("文本内容超过1MiB，请拆分文档")
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding, warnings


def docx_entries(document, styles=None, *, content=None) -> list[dict]:
    """Shared labelled paragraphs and adjacent-cell evidence for DOCX consumers."""
    from .docx_semantics import read_docx_content
    content = content if content is not None else read_docx_content(document, styles)
    entries = []
    visible_text = {id(paragraph.element): paragraph.text for paragraph in content.paragraphs}
    rows = []
    cell_following_text = {}
    for row in document.findall(".//w:tr", NS):
        elements = row.findall("w:tc", NS)
        cells = [" ".join(visible_text.get(id(node), "") for node in cell.findall(".//w:p", NS)).strip() for cell in elements]
        rows.append(cells)
        for index, cell in enumerate(elements):
            for node in cell.findall(".//w:p", NS):
                cell_following_text[id(node)] = cells[index + 1] if index + 1 < len(cells) else None
    for paragraph in content.paragraphs:
        index, text = paragraph.index, paragraph.text
        if text:
            entries.append({"text": text, "location": f"XML段{index}：{text[:100]}", "method": "text", "docx_paragraph": index,
                            **({"table_cell": True, "table_following_text": cell_following_text[id(paragraph.element)]}
                               if id(paragraph.element) in cell_following_text else {})})
    for row_number, cells in enumerate(rows, 1):
        for index in range(len(cells) - 1):
            if cells[index]:
                entries.append({"text": cells[index] + "：" + cells[index + 1],
                                "location": f"表格行{row_number}，单元格{index + 1}–{index + 2}", "method": "text", "table_pair": True,
                                "docx_table_row": row_number, "table_label": cells[index], "table_value": cells[index + 1]})
    return entries


def _read_docx(path: Path) -> dict[str, Any]:
    from .docx_semantics import read_docx_content
    package = read_docx(path)
    content = read_docx_content(package["document"], package["styles"], numbering=package.get("numbering"),
                                styles_reason=package.get("styles_reason", ""))
    package["content"] = content
    entries = docx_entries(package["document"], content=content)
    text = "\n".join(entry["text"] for entry in entries if not entry.get("table_pair"))
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("DOCX 提取正文超过1MiB，请拆分文档")
    return {"format": "docx", "text": text, "entries": entries, "pages": [], "warnings": content.warnings,
            "complete": True, "requires_review": content.requires_review, "docx": package}


def _read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 2 * MAX_TEXT_BYTES:
        raise ValueError("JSON 文件超过2MiB，请拆分材料")
    text, encoding, warnings = _read_text(path)

    def object_pairs(pairs):
        mapping = {}
        for property_name, property_value in pairs:
            if property_name in mapping:
                raise ValueError("JSON 含重复键：" + property_name[:100])
            mapping[property_name] = property_value
        return mapping

    def invalid_constant(_constant):
        raise ValueError("JSON 不允许 NaN 或 Infinity")

    try:
        data = json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("JSON 格式无效或嵌套过深") from exc
    count = 0

    def check_limits(node, depth=0):
        nonlocal count
        count += 1
        if depth > 40 or count > 50_000:
            raise ValueError("JSON 嵌套超过40层或内容超过5万项，请拆分材料")
        if isinstance(node, dict):
            for child in node.values():
                check_limits(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                check_limits(child, depth + 1)
        elif isinstance(node, float) and not math.isfinite(node):
            raise ValueError("JSON 数字必须为有限值")

    check_limits(data)
    labels = {"name": "姓名", "student_id": "学号", "organization": "实习单位", "start_date": "开始日期", "end_date": "结束日期"}
    entries = []

    def add_entry(raw_text, json_pointer, **metadata):
        if not isinstance(raw_text, str) or not raw_text.strip():
            return
        entries.append({"text": raw_text.strip(), "location": "JSON Pointer " + (json_pointer or "/"), "method": "text", **metadata})

    schema = data.get("schema") if isinstance(data, dict) else None
    if isinstance(data, dict) and "schema" in data and schema != "formatly.document.v1":
        raise ValueError("不支持的 JSON 文档 schema；请使用 formatly.document.v1 或不带 schema 的普通 JSON")
    if schema == "formatly.document.v1":
        if set(data) - {"schema", "title", "paragraphs", "fields"}:
            raise ValueError("formatly.document.v1 仅支持 schema、title、paragraphs、fields")
        if "title" in data and not isinstance(data["title"], str):
            raise ValueError("JSON title 须为文本")
        paragraphs, fields = data.get("paragraphs", []), data.get("fields", {})
        if not isinstance(paragraphs, list) or not isinstance(fields, dict):
            raise ValueError("JSON paragraphs 须为数组，fields 须为对象")
        add_entry(data.get("title"), "/title", role="heading", level=1)
        for paragraph_index, paragraph in enumerate(paragraphs):
            paragraph_pointer = f"/paragraphs/{paragraph_index}"
            if isinstance(paragraph, str):
                add_entry(paragraph, paragraph_pointer, role="body")
                continue
            if (not isinstance(paragraph, dict) or set(paragraph) - {"text", "role", "level"}
                    or not isinstance(paragraph.get("text"), str) or paragraph.get("role", "body") not in {"heading", "body"}
                    or ("level" in paragraph and (type(paragraph["level"]) is not int or not 1 <= paragraph["level"] <= 6))):
                raise ValueError("JSON paragraphs 项须为文本或有效的 text/role/level 对象")
            add_entry(paragraph["text"], paragraph_pointer + "/text", role=paragraph.get("role", "body"), level=paragraph.get("level", 1))
        for field_name, field_value in fields.items():
            if field_name not in labels or not isinstance(field_value, str):
                raise ValueError("JSON fields 仅支持姓名、学号、单位及起止日期的文本值")
            add_entry(labels[field_name] + "：" + field_value, "/fields/" + field_name, field=field_name)
    else:
        def walk(node, current_pointer="", label_key=None):
            if isinstance(node, str):
                add_entry((labels[label_key] + "：" + node) if label_key in labels else node,
                          current_pointer, **({"field": label_key} if label_key in labels else {}))
            elif isinstance(node, dict):
                for property_key, child_value in node.items():
                    walk(child_value, current_pointer + "/" + property_key.replace("~", "~0").replace("/", "~1"), property_key)
            elif isinstance(node, list):
                for child_index, child_value in enumerate(node):
                    walk(child_value, current_pointer + "/" + str(child_index))
        walk(data)
        warnings.append("普通 JSON 仅提取字符串及明确字段；键名、数字和对象结构不作为实际排版属性")
    extracted = "\n".join(item["text"] for item in entries)
    if len(extracted.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("JSON 提取文本超过1MiB，请拆分材料")
    return {"format": "json", "text": extracted, "entries": entries, "pages": [], "encoding": encoding,
            "json_schema": schema,
            "structured_fields": dict(data["fields"]) if schema == "formatly.document.v1" and "fields" in data else None,
            "warnings": warnings, "complete": True, "requires_review": encoding == "gb18030"}


def _read_pdf(path: Path, output_dir, ocr: bool) -> dict[str, Any]:
    if not path.read_bytes()[:1024].lstrip().startswith(b"%PDF-"):
        raise ValueError("PDF 签名无效")
    available, reason = probe_pdf()
    if not available:
        raise ValueError(reason)
    parent = Path(output_dir) if output_dir is not None else path.parent
    parent.mkdir(parents=True, exist_ok=True)
    with pdf_working_directory(parent) as temporary:
        output = temporary / "extraction.json"
        command = [sys.executable, "-B", "-m", "formatly.documents.worker", str(path.resolve()), str(output), "1" if ocr else "0"]
        try:
            with managed_python_worker(command, cwd=Path(__file__).resolve().parents[2]) as process:
                process.wait(timeout=PDF_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("PDF 解析超过150秒限制，请拆分文件或检查 PDF 是否损坏") from exc
        if not output.is_file() or output.stat().st_size > MAX_WORKER_BYTES:
            raise ValueError("PDF 解析进程未返回有效结果或证据超限")
        try:
            result = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("PDF 解析结果不可读") from exc
        if process.returncode or "error" in result:
            raise ValueError(result.get("error", "PDF 解析失败"))
        return result


def read_document(path, *, output_dir=None, ocr=True) -> dict[str, Any]:
    path = Path(path)
    kind = document_format(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("文档为空、不存在或超过40MB限制")
    document: dict[str, Any]
    if kind == "docx":
        document = _read_docx(path)
    elif kind == "pdf":
        document = _read_pdf(path, output_dir, bool(ocr))
    elif kind == "json":
        document = _read_json(path)
    else:
        text, encoding, warnings = _read_text(path)
        entries = [{"text": line.strip(), "location": f"{'Markdown' if kind == 'md' else '文本'}第{index}行", "method": "text"}
                   for index, line in enumerate(text.splitlines(), 1) if line.strip()]
        document = {"format": kind, "text": text, "encoding": encoding, "entries": entries, "pages": [],
                    "warnings": warnings, "complete": True, "requires_review": bool(warnings)}
    from .field_coverage import field_text_coverage
    ocr_information = document.get("ocr")
    if isinstance(ocr_information, dict):
        document["ocr"] = public_ocr_information(ocr_information)
    document["field_text_coverage"] = field_text_coverage(document)
    return document
