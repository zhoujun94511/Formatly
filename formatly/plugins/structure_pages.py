"""Read active section numbering and related PAGE fields without rendering."""
from __future__ import annotations

import posixpath
import re
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError, fromstring
from zipfile import ZipFile

from ..documents.docx_semantics import read_docx_content
from ..files import NS, W
from ..privacy import redact_local_paths

REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _xml(archive: ZipFile, name: str) -> Element:
    raw = archive.read(name)
    declarations = raw.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("页码相关部件包含XML声明，须人工核对")
    return fromstring(raw)


def _page_field(root: Element, styles: Element | None, styles_reason="") -> tuple[bool, str]:
    content = read_docx_content(root, styles, styles_reason=styles_reason)
    if content.requires_review:
        return False, "页眉页脚包含隐藏、修订或兼容分支，页码域须人工核对"
    visible = {run.element for paragraph in content.paragraphs for run in paragraph.runs}
    parents = {child: parent for parent in root.iter() for child in parent}
    stack: list[dict] = []
    found = False
    for element in root.iter():
        if element.tag == W + "fldSimple":
            command = element.get(W + "instr", "").strip().split()
            if command and command[0].upper() == "PAGE":
                # Simple fields inside inactive branches are excluded too.
                runs = element.findall(".//w:r", NS)
                if runs and any(run in visible for run in runs):
                    found = True
                elif not runs:
                    return False, "PAGE域尚无结果内容，须更新并核对域"
            continue
        if element.tag not in {W + "fldChar", W + "instrText"}:
            continue
        parent = parents.get(element)
        while parent is not None and parent.tag != W + "r":
            parent = parents.get(parent)
        if parent not in visible:
            continue
        if element.tag == W + "instrText":
            if stack and not stack[-1]["separated"]:
                stack[-1]["instruction"] += element.text or ""
            else:
                return False, "页眉页脚有不完整的复杂域指令"
            continue
        kind = element.get(W + "fldCharType")
        if kind == "begin":
            stack.append({"instruction": "", "separated": False})
        elif kind == "separate" and stack:
            stack[-1]["separated"] = True
        elif kind == "end" and stack:
            field = stack.pop()
            command = field["instruction"].strip().split()
            if command and command[0].upper() == "PAGE":
                if not field["separated"]:
                    return False, "PAGE域缺少结果分隔，须更新并核对域"
                found = True
        else:
            return False, "页眉页脚复杂域边界无效"
    return (False, "页眉页脚复杂域未闭合") if stack else (found, "")


def section_page_fields(path: Path, sections: list[Element], styles: Element | None, *, styles_reason="") -> list[tuple[bool, str, list[str]]]:
    """Resolve default header/footer inheritance; never infer printed numbers."""
    try:
        with ZipFile(path) as archive:
            parts = set(archive.namelist())
            relationships: dict[str, tuple[str, str]] = {}
            rel_name = "word/_rels/document.xml.rels"
            if rel_name in parts:
                rels = _xml(archive, rel_name)
                if rels.tag != REL + "Relationships":
                    raise ValueError("主文档关系命名空间无效")
                for relation in rels.findall(REL + "Relationship"):
                    identity = relation.get("Id", "")
                    target = relation.get("Target", "")
                    if identity in relationships:
                        raise ValueError("主文档含重复关系ID")
                    if relation.get("TargetMode", "Internal") != "Internal" or "\\" in target or re.search(r"[%?#:]", target):
                        relationships[identity] = ("", "")
                        continue
                    name = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "word/" + target)
                    if not name.startswith("word/") or name not in parts:
                        relationships[identity] = ("", "")
                        continue
                    relationships[identity] = (name, relation.get("Type", "").rsplit("/", 1)[-1])
            variants = ["default"]
            if "word/settings.xml" in parts:
                settings = _xml(archive, "word/settings.xml")
                if settings.tag != W + "settings":
                    raise ValueError("文档设置命名空间无效")
                even = settings.find("w:evenAndOddHeaders", NS)
                if even is not None:
                    flag = even.get(W + "val", "true").lower()
                    if flag not in {"true", "1", "on", "false", "0", "off"}:
                        raise ValueError("奇偶页页眉页脚设置无法确定")
                    if flag in {"true", "1", "on"}:
                        variants.append("even")
            inherited: dict[tuple[str, str], tuple[str, str]] = {}
            result = []
            observed: dict[str, tuple[bool, str]] = {}
            for section in sections:
                errors = []
                seen = set()
                for kind in ("header", "footer"):
                    for reference in section.findall("w:" + kind + "Reference", NS):
                        variant = reference.get(W + "type", "default")
                        if variant not in {"default", "even", "first"}:
                            errors.append("页眉页脚变体类型无效")
                        key = kind, variant
                        if key in seen:
                            errors.append("同一分节重复声明页眉页脚")
                        seen.add(key)
                        target = relationships.get(reference.get(RID, ""), ("", ""))
                        inherited[key] = target if target[1] == kind else ("", "")
                names = []
                successes = []
                for variant in variants:
                    present = False
                    for kind in ("header", "footer"):
                        target = inherited.get((kind, variant))
                        if target is None:
                            continue
                        name = target[0]
                        if not name:
                            errors.append("页眉页脚关系缺失、外部引用或目标不可读")
                            continue
                        names.append(name)
                        if name not in observed:
                            xml = _xml(archive, name)
                            if xml.tag != W + ("hdr" if kind == "header" else "ftr"):
                                observed[name] = False, "页眉页脚根节点类型不符"
                            else:
                                observed[name] = _page_field(xml, styles, styles_reason)
                        has_page, reason = observed[name]
                        present |= has_page
                        if reason:
                            errors.append(reason)
                    successes.append(present)
                result.append((all(successes), "；".join(dict.fromkeys(errors)), sorted(set(names))))
            return result
    except (KeyError, OSError, ParseError, ValueError) as exc:
        return [(False, "页码部件无法安全读取：" + redact_local_paths(str(exc)), []) for _ in sections]
