"""Bounded document reads and atomic artifact writes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from xml.etree.ElementTree import ParseError, fromstring
from zipfile import BadZipFile, ZipFile

MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                # Windows readers and scanners can briefly deny replacement.
                # Keep the old file intact, and never turn permanent errors
                # into an unbounded wait or a non-atomic overwrite.
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 5:
                    raise
                time.sleep(.01 * 2 ** attempt)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_docx(path: Path) -> dict:
    if path.suffix.lower() != ".docx":
        raise ValueError("仅支持 .docx 文档；.doc 文档请先另存为 DOCX")
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("文档为空、不存在或超过40MB限制")
    try:
        with ZipFile(path) as package:
            entries = package.infolist()
            names = [item.filename for item in entries]
            if len(entries) > 5000 or len(set(names)) != len(names):
                raise ValueError("DOCX条目过多或包含重名部件")
            if sum(item.file_size for item in entries) > MAX_PACKAGE_BYTES:
                raise ValueError("DOCX解压后超过100MB限制")
            if any(item.flag_bits & 1 for item in entries):
                raise ValueError("不支持加密的DOCX包")
            if any(".." in Path(name.replace("\\", "/")).parts or name.startswith(("/", "\\")) for name in names):
                raise ValueError("DOCX包含不安全的部件路径")
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            if not required.issubset(names):
                raise ValueError("不是完整的DOCX包：缺少必需部件")
            parsed = {}
            for name in required:
                raw = package.read(name)
                # NUL removal also recognizes UTF-16/32 declaration spellings.
                declarations = raw.replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                    raise ValueError("不接受包含DTD或实体声明的XML")
                parsed[name] = fromstring(raw)
            if parsed["word/document.xml"].tag != W + "document":
                raise ValueError("文档XML命名空间不受支持")
            if parsed["word/document.xml"].find("w:body", NS) is None:
                raise ValueError("DOCX缺少正文body部件")
            types = parsed["[Content_Types].xml"]
            types_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
            if types.tag != types_ns + "Types" or not any(
                item.get("PartName") == "/word/document.xml" and item.get("ContentType") ==
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                for item in types.findall(types_ns + "Override")
            ):
                raise ValueError("DOCX缺少有效的主文档内容类型")
            rels = parsed["_rels/.rels"]
            rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
            if rels.tag != rel_ns + "Relationships" or not any(
                item.get("Type") == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
                and item.get("Target", "").lstrip("/") == "word/document.xml" and item.get("TargetMode", "Internal") == "Internal"
                for item in rels.findall(rel_ns + "Relationship")
            ):
                raise ValueError("DOCX缺少有效的主文档包关系")
            from .documents.docx_numbering import read_numbering
            from .documents.ooxml import read_related_xml
            styles = read_related_xml(
                package, types, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
                W + "styles", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml", "样式",
                allow_absent=True, conventional_part="word/styles.xml")
            style_reason = styles.reason
            if styles.root is None and not style_reason and any(
                node.tag in {W + "pStyle", W + "rStyle", W + "tblStyle"} for node in parsed["word/document.xml"].iter()
            ):
                style_reason = "文档引用了未提供有效部件关系的样式"
            return {"document": parsed["word/document.xml"], "styles": styles.root,
                    "styles_reason": style_reason, "styles_part": styles.part,
                    "numbering": read_numbering(package, types),
                    "parts": names, "uncompressed_bytes": sum(e.file_size for e in entries)}
    except (BadZipFile, ParseError, RuntimeError) as exc:
        raise ValueError(f"DOCX损坏或XML不可读: {exc}") from exc


def safe_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("文件路径超出任务目录")
    return path

