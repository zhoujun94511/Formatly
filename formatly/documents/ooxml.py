"""Shared lexical values and bounded internal OPC XML relationships."""
from __future__ import annotations

from dataclasses import dataclass
import posixpath
import re
from xml.etree.ElementTree import Element, ParseError, fromstring
from zipfile import ZipFile

MAX_RELATED_XML_BYTES = 8 * 1024 * 1024
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def parse_on_off(value: str | None, *, default: bool | None = None) -> bool | None:
    """Read all ST_OnOff spellings; an invalid value remains unknown."""
    if value is None:
        return default
    raw = value.strip().lower()
    if raw in {"true", "1", "on"}:
        return True
    if raw in {"false", "0", "off"}:
        return False
    return None


@dataclass(frozen=True)
class RelatedXml:
    root: Element | None = None
    part: str | None = None
    reason: str = ""


def read_related_xml(package: ZipFile, types: Element, relationship_type: str, root_tag: str,
                     content_type: str, label: str, *, allow_absent=False, conventional_part="") -> RelatedXml:
    """Resolve one internal main-document relationship without filename fallback.

    Optional absent parts remain absent. Invalid, duplicated or unresolved
    relationships return an explicit reason instead of an unrelated XML tree.
    """
    def xml(part_name: str) -> Element:
        if not 0 < package.getinfo(part_name).file_size <= MAX_RELATED_XML_BYTES:
            raise ValueError(f"{label}部件或关系为空或超过8MiB读取限制")
        raw = package.read(part_name)
        markup = raw.replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in markup or b"<!ENTITY" in markup:
            raise ValueError(f"{label}部件或关系包含不支持的XML声明")
        return fromstring(raw)

    def absent() -> RelatedXml:
        declared = any(node.get("ContentType") == content_type for node in types)
        orphan = conventional_part and conventional_part in package.namelist()
        if allow_absent and not declared and not orphan:
            return RelatedXml()
        return RelatedXml(reason=f"{label}部件关系不存在或不唯一")

    try:
        if "word/_rels/document.xml.rels" not in package.namelist():
            return absent()
        relationships = xml("word/_rels/document.xml.rels")
        if relationships.tag != _REL + "Relationships":
            raise ValueError("主文档关系命名空间无效")
        entries = relationships.findall(_REL + "Relationship")
        matches = [node for node in entries if node.get("Type") == relationship_type]
        if not matches:
            return absent()
        if len(matches) != 1:
            raise ValueError(f"{label}部件关系不存在或不唯一")
        relation = matches[0]
        identity = relation.get("Id")
        if not identity or sum(node.get("Id") == identity for node in entries) != 1:
            raise ValueError(f"{label}部件关系ID无效或重复")
        target = relation.get("Target", "")
        if (not target or len(target) > 4096 or relation.get("TargetMode", "Internal") != "Internal"
                or "\\" in target or re.search(r"[%?#:\s\x00-\x1f]", target) or target.startswith("//")):
            raise ValueError(f"{label}部件不是可读取的内部关系")
        name = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "word/" + target)
        if name.startswith(("../", "/")) or name in {".", ".."}:
            raise ValueError(f"{label}部件关系路径无效")
        declarations = [node for node in types.findall(_TYPES + "Override") if node.get("PartName") == "/" + name]
        if not declarations:
            extension = posixpath.splitext(name)[1].removeprefix(".").lower()
            declarations = [node for node in types.findall(_TYPES + "Default")
                            if node.get("Extension", "").lower() == extension]
        if len(declarations) != 1 or declarations[0].get("ContentType") != content_type:
            raise ValueError(f"{label}部件内容类型缺失、无效或不唯一")
        root = xml(name)
        if root.tag != root_tag:
            raise ValueError(f"{label}定义XML命名空间无效")
        return RelatedXml(root=root, part=name)
    except (KeyError, ParseError, ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else f"{label}部件、关系或XML无法读取"
        return RelatedXml(reason=reason)
