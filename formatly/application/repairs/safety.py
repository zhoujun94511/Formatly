"""DOCX package and page geometry safety gates for repairs."""
from __future__ import annotations

import re
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError, fromstring
from zipfile import ZipFile

from ...files import NS, W

_REVISIONS = {W + name for name in ("ins", "del", "moveFrom", "moveTo", "moveFromRangeStart",
                                   "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd", "trackRevisions",
                                   "cellIns", "cellDel", "cellMerge", "numberingChange", "delText")}
def _part_safety(path: Path, package: dict) -> tuple[bytes, str]:
    if package.get("styles_reason"):
        return b"", "样式部件或关系无法确认，不能自动修复：" + package["styles_reason"]
    with ZipFile(path) as archive:
        if any(name.lower().startswith("_xmlsignatures/") or name.lower().endswith("vbaproject.bin") for name in package["parts"]):
            return b"", "含数字签名或宏的文档不支持自动修复"
        # OPC locates signatures through relationships and content types. Their
        # parts need not use Word's usual _xmlsignatures directory.
        for name in package["parts"]:
            if name != "[Content_Types].xml" and not name.lower().endswith(".rels"):
                continue
            data = archive.read(name)
            declarations = data.replace(b"\0", b"").upper()
            if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                return b"", "文档包关系含不支持的 XML 声明，不能自动修复"
            try:
                root = fromstring(data)
            except ParseError:
                return b"", "文档包关系不完整，不能自动修复"
            for node in root.iter():
                content_type = node.get("ContentType", "").casefold()
                relationship = node.get("Type", "").casefold()
                if ("/relationships/digital-signature/" in relationship
                        or content_type.startswith("application/vnd.openxmlformats-package.digital-signature")
                        or relationship.endswith("/vbaproject")
                        or "vbaproject" in content_type or "macroenabled" in content_type):
                    return b"", "含数字签名或宏的文档不支持自动修复"
        raw = archive.read("word/document.xml")
        for name in package["parts"]:
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            data = raw if name == "word/document.xml" else archive.read(name)
            upper = data.replace(b"\0", b"").upper()
            if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                return b"", "文档含不支持的 XML 声明，不能自动修复"
            try:
                root = fromstring(data)
            except ParseError:
                return b"", "文档部件 XML 不完整，不能自动修复"
            for node in root.iter():
                if (node.tag == W + "documentProtection"
                        and node.get(W + "enforcement", "").strip().lower() in {"0", "false", "off"}):
                    # Word may retain protection settings with enforcement
                    # explicitly disabled. Preserve the settings unchanged.
                    continue
                if node.tag in {W + "documentProtection", W + "writeProtection"}:
                    return b"", "受保护文档不支持自动修复"
                if node.tag in _REVISIONS or (node.tag.startswith(W) and node.tag.endswith("Change")):
                    return b"", "文档含修订记录或已开启修订，请先在 Word/WPS 中处理修订"
        try:
            raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return b"", "此 XML 编码暂不支持自动修复，请使用 Word/WPS 另存为 DOCX"
        encoding = re.search(rb'<\?xml[^>]*encoding\s*=\s*[\'"]([^\'"]+)', raw[:200], re.I)
        if encoding and encoding.group(1).lower() not in {b"utf-8", b"utf8", b"us-ascii"}:
            return b"", "此 XML 编码暂不支持自动修复，请使用 Word/WPS 另存为 DOCX"
    return raw, ""

def _enabled(element: Element | None) -> bool:
    if element is None:
        return False
    value = element.get(W + "val", "1").strip().lower()
    if value not in {"1", "true", "on", "0", "false", "off"}:
        raise ValueError("页面方向设置无法确定，请先在 Word/WPS 中核对")
    return value in {"1", "true", "on"}

def _validate_page_geometry(section: Element, settings: Element | None = None) -> None:
    size, margins = section.find("w:pgSz", NS), section.find("w:pgMar", NS)
    if size is None or margins is None:
        return
    setting = lambda name: settings.find("w:" + name, NS) if settings is not None else None
    if any(_enabled(setting(name)) for name in ("bookFoldPrinting", "bookFoldRevPrinting", "printTwoOnOne")):
        raise ValueError("书籍折页或每页多版的页面设置需在 Word/WPS 中人工修改")
    try:
        gutter = int(margins.get(W + "gutter", "0"))
    except ValueError as exc:
        raise ValueError("装订线不是有效的 DOCX 数值，请先在 Word/WPS 中核对") from exc
    if gutter < 0:
        raise ValueError("装订线不能为负值，请先在 Word/WPS 中核对")
    direction = section.find("w:textDirection", NS)
    if gutter and direction is not None and direction.get(W + "val", "lrTb") != "lrTb":
        raise ValueError("竖排文档的装订线页面设置需在 Word/WPS 中人工修改")
    # Mirrored margins bind on the inside edge, even when gutterAtTop is set.
    gutter_axis = "h" if _enabled(setting("gutterAtTop")) and not _enabled(setting("mirrorMargins")) else "w"
    for dimension, first, second in (("w", "left", "right"), ("h", "top", "bottom")):
        raw_extent = size.get(W + dimension)
        raw_start = margins.get(W + first)
        raw_end = margins.get(W + second)
        if raw_extent is None or raw_start is None or raw_end is None:
            continue
        try:
            extent, start, end = int(raw_extent), int(raw_start), int(raw_end)
        except ValueError as exc:
            raise ValueError("页面属性不是有效的 DOCX 数值，请先在 Word/WPS 中核对") from exc
        binding = gutter if dimension == gutter_axis else 0
        if extent <= 0 or start < 0 or end < 0 or start + end + binding >= extent:
            raise ValueError("所选纸张、页边距与装订线组合没有有效正文空间，请调整方案或同时修复相关项目")
