"""Separate explicit document roles from paragraph styles used by body rules."""
from __future__ import annotations

import re
from xml.etree.ElementTree import Element

from ..files import NS, W
from .docx_semantics import DocxParagraph, default_paragraph_style, paragraph_properties, paragraph_style

_ABSTRACT_HEADINGS = {"摘要", "中文摘要", "英文摘要", "abstract"}
_STRUCTURAL_HEADINGS = {"目录", "目次", "contents", "tableofcontents", "参考文献", "references",
                        "bibliography", "致谢", "acknowledgments", "acknowledgements", "附录", "appendix", "appendices"}
_KEYWORD_PREFIX = re.compile(r"^\s*(?:关\s*键\s*词|key\s*words?)\s*[:：]", re.I)
_CAPTION_PREFIX = re.compile(r"^\s*(?:[图表]\s*|(?:table|figure|fig\.)\s+)[0-9]+(?:[.．\-－][0-9]+)*\s+\S", re.I)
_NOTE_PREFIX = re.compile(r"^\s*(?:注|说明|notes?)\s*[:：]", re.I)


def _normalize(text: str) -> str:
    return "".join(text.split()).casefold()


def _after_table(document: Element, paragraphs: list[DocxParagraph]) -> set[int]:
    """Identify only the next visible body paragraph after an actual table block."""
    visible = {paragraph.element: paragraph.index for paragraph in paragraphs if paragraph.text.strip()}
    result: set[int] = set()
    previous: str | None = None

    def visit(container: Element) -> None:
        nonlocal previous
        for node in container:
            if node.tag == W + "p":
                if node in visible:
                    if previous == "table":
                        result.add(visible[node])
                    previous = "paragraph"
            elif node.tag == W + "tbl":
                previous = "table"
            elif node.tag == W + "sdt":
                content = node.find("w:sdtContent", NS)
                if content is not None:
                    visit(content)
                else:
                    previous = None
            elif node.tag in {W + "customXml", W + "ins", W + "moveTo"}:
                visit(node)
            else:
                previous = None

    body = document.find("w:body", NS)
    if body is not None:
        visit(body)
    return result


def body_scope_roles(document: Element, styles: Element | None,
                     paragraphs: list[DocxParagraph], *, exclude_containers: bool = False) -> dict[int, tuple[str, str]]:
    """Return exclusions or uncertainty backed by explicit structure, never font appearance.

    The unmarked paragraph immediately before an abstract heading is ambiguous:
    preserve its measured properties for review instead of authorizing a body repair.
    """
    indexed = {} if styles is None else {style.get(W + "styleId"): style for style in styles.findall("w:style", NS)}
    parents = {child: parent for parent in document.iter() for child in parent}
    roles: dict[int, tuple[str, str]] = {}
    explicit_body = set()
    default_style = default_paragraph_style(styles)
    after_table = _after_table(document, paragraphs)
    for paragraph in paragraphs:
        text = _normalize(paragraph.text)
        if not text:
            continue
        if text in _ABSTRACT_HEADINGS:
            roles[paragraph.index] = ("abstract_heading", "独立摘要标题")
            continue
        if text in _STRUCTURAL_HEADINGS:
            roles[paragraph.index] = ("structural_heading", "独立结构标题")
            continue
        node: Element | None = paragraph.element
        while node is not None:
            if exclude_containers and node.tag in {W + "tc", W + "txbxContent"}:
                roles[paragraph.index] = ("table" if node.tag == W + "tc" else "textbox", "表格或文本框中的文字不作为正文段落要求")
                break
            if node.tag == W + "sdt":
                gallery = node.find("w:sdtPr/w:docPartObj/w:docPartGallery", NS)
                if gallery is not None and _normalize(gallery.get(W + "val", "")) in {"tableofcontents", "目录"}:
                    roles[paragraph.index] = ("toc", "目录内容控件")
                    break
            if node.tag == W + "fldSimple" and re.match(r"\s*TOC(?:\s|$)", node.get(W + "instr", ""), re.I):
                roles[paragraph.index] = ("toc", "目录域")
                break
            node = parents.get(node)
        if paragraph.index in roles:
            continue
        properties = paragraph_properties(paragraph, styles, uncertainty=paragraph.property_uncertainty)
        outline = properties.get(W + "outlineLvl", {}).get(W + "val")
        if outline in {str(level) for level in range(9)}:
            roles[paragraph.index] = ("heading", "显式或继承的大纲标题级别")
            continue
        identity: str | None = paragraph_style(paragraph.element, styles)
        seen = set()
        while identity and identity not in seen:
            seen.add(identity)
            style = indexed.get(identity)
            name = style.find("w:name", NS) if style is not None else None
            names = {_normalize(identity), _normalize(name.get(W + "val", "")) if name is not None else ""}
            if any(re.fullmatch(r"(?:heading|标题)[1-9]", item) for item in names):
                if outline != "9":
                    roles[paragraph.index] = ("heading", "标题样式及其继承关系")
                break
            if names & {"title", "subtitle", "标题", "副标题"}:
                roles[paragraph.index] = ("title", "题名或副标题样式")
                break
            if names & {"caption", "题注"}:
                roles[paragraph.index] = ("caption", "图表题注样式")
                break
            if any(re.fullmatch(r"(?:toc|目录)[1-9]", item) for item in names) or names & {"tocheading", "目录标题"}:
                roles[paragraph.index] = ("toc", "目录样式及其继承关系")
                break
            if identity != default_style and names & {"bodytext", "正文"}:
                explicit_body.add(paragraph.index)
            parent_style = style.find("w:basedOn", NS) if style is not None else None
            identity = parent_style.get(W + "val") if parent_style is not None else None
        if paragraph.index not in roles:
            if _KEYWORD_PREFIX.match(paragraph.text):
                roles[paragraph.index] = ("uncertain", "关键词标签与内容可能适用不同格式；保留实际属性，须核对该段格式要求")
            elif _CAPTION_PREFIX.match(paragraph.text):
                roles[paragraph.index] = ("uncertain", "编号图表标题可能适用独立格式；保留实际属性，须核对是否适用正文要求")
            elif paragraph.index in after_table and _NOTE_PREFIX.match(paragraph.text):
                roles[paragraph.index] = ("uncertain", "表格后带说明标签的段落可能适用独立格式；保留实际属性，须核对该段格式要求")
    previous: DocxParagraph | None = None
    for paragraph in paragraphs:
        if not paragraph.text.strip():
            continue
        if (roles.get(paragraph.index, (None, ""))[0] == "abstract_heading" and previous is not None
                and previous.index not in roles and previous.index not in explicit_body):
            roles[previous.index] = ("uncertain", "摘要标题前的相邻段落角色未确认；保留实际属性，须核对是否适用正文要求")
        previous = paragraph
    return roles
