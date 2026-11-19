"""Byte-preserving XML mutation helpers for DOCX repairs."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from xml.parsers import expat
from xml.sax.saxutils import escape

from ...files import NS, W

_ORDERS = {
    "pPr": "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange".split(),
    "rPr": "rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange".split(),
}

@dataclass
class _Span:
    path: tuple[int, ...]
    tag: str
    qname: str
    start: int
    opening_end: int
    end_start: int
    end: int
    namespaces: dict[str, str]
    children: list['_Span'] = field(default_factory=list)

def _tag_end(raw: bytes, start: int) -> int:
    quote = None
    for index in range(start, len(raw)):
        character = raw[index]
        if quote is not None:
            if character == quote:
                quote = None
        elif character in (34, 39):
            quote = character
        elif character == 62:
            return index + 1
    raise ValueError("XML 标签未闭合")

def _spans(raw: bytes) -> dict[tuple[int, ...], _Span]:
    parser = expat.ParserCreate(namespace_separator="}")
    stack: list[_Span] = []
    pending_namespaces: dict[str, str] = {}
    result = {}
    def namespace(prefix, uri):
        pending_namespaces[prefix or ""] = uri
    def start(name, _attrs):
        offset = parser.CurrentByteIndex
        opening_end = _tag_end(raw, offset)
        name_match = re.match(rb'<([^\s/>]+)', raw[offset:opening_end])
        if name_match is None:
            raise ValueError("XML 开始标签缺少有效名称")
        qname = name_match.group(1).decode("utf-8")
        path = stack[-1].path + (len(stack[-1].children),) if stack else ()
        bindings = {**(stack[-1].namespaces if stack else {}), **pending_namespaces}
        pending_namespaces.clear()
        node = _Span(path, "{" + name if "}" in name else name, qname, offset, opening_end, opening_end, opening_end, bindings)
        if stack:
            stack[-1].children.append(node)
        result[path] = node
        stack.append(node)
    def end(_name):
        node = stack.pop()
        if not raw[node.start:node.opening_end].rstrip().endswith(b"/>"):
            node.end_start = parser.CurrentByteIndex
            node.end = _tag_end(raw, node.end_start)
    parser.StartNamespaceDeclHandler = namespace
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(raw, True)
    return result

def _word_prefix(namespaces: dict[str, str]) -> tuple[str, bool]:
    for prefix, uri in namespaces.items():
        if prefix and uri == NS["w"]:
            return prefix, False
    prefix = "fmtw"
    while prefix in namespaces:
        prefix += "w"
    return prefix, True

def _attribute_value(value: str) -> bytes:
    return escape(value, {'"': "&quot;", "'": "&apos;"}).encode("utf-8")

def _start_attributes(raw: bytes, node: _Span, updates: dict[str, str]) -> bytes:
    opening = raw[node.start:node.opening_end]
    edits = []
    remaining = dict(updates)
    for match in re.finditer(rb'''([^\s=<>/'"]+)\s*=\s*(["'])(.*?)\2''', opening, re.S):
        name = match.group(1).decode("utf-8")
        if ":" not in name:
            continue
        prefix, local = name.split(":", 1)
        if node.namespaces.get(prefix) == NS["w"] and local in remaining:
            edits.append((match.start(3), match.end(3), _attribute_value(remaining.pop(local))))
    if remaining:
        prefix, declare = _word_prefix(node.namespaces)
        addition = (f' xmlns:{prefix}="{NS["w"]}"'.encode("utf-8") if declare else b"")
        addition += b"".join(b" " + f"{prefix}:{name}".encode("utf-8") + b'="' + _attribute_value(value) + b'"' for name, value in remaining.items())
        offset = len(opening) - (2 if opening.endswith(b"/>") else 1)
        edits.append((offset, offset, addition))
    for start, end, replacement in sorted(edits, reverse=True):
        opening = opening[:start] + replacement + opening[end:]
    return opening

@dataclass
class _Mutation:
    tag: str
    span: _Span | None
    attributes: dict[str, str] = field(default_factory=dict)
    children: dict[str, '_Mutation'] = field(default_factory=dict)

def _put(root: _Mutation, chain: list[str], attributes: dict[str, str]) -> None:
    node = root
    for local in chain:
        if local not in node.children:
            found = [child for child in node.span.children if child.tag == W + local] if node.span else []
            if len(found) > 1:
                raise ValueError("格式属性重复，不能自动修复")
            node.children[local] = _Mutation(local, found[0] if found else None)
        node = node.children[local]
    for key, value in attributes.items():
        if key in node.attributes and node.attributes[key] != value:
            raise ValueError("所选修复存在相互冲突的格式要求")
        node.attributes[key] = value

def _rank(parent: str, local: str) -> int:
    order = _ORDERS.get(parent, [])
    return order.index(local) if local in order else len(order)

def _new_xml(node: _Mutation, namespaces: dict[str, str]) -> bytes:
    prefix, declare = _word_prefix(namespaces)
    name = (prefix + ":" + node.tag).encode("utf-8")
    declaration = f' xmlns:{prefix}="{NS["w"]}"'.encode("utf-8") if declare else b""
    attribute_map: dict[str, str] = node.attributes
    serialized_attributes = [
        b" " + f"{prefix}:{key}".encode("utf-8") + b'="' + _attribute_value(value) + b'"'
        for key, value in attribute_map.items()
    ]
    attributes = declaration + b"".join(serialized_attributes)
    content = b"".join(_new_xml(child, {**namespaces, prefix: NS["w"]}) for child in sorted(node.children.values(), key=lambda child: _rank(node.tag, child.tag)))
    return b"<" + name + attributes + (b">" + content + b"</" + name + b">" if content else b"/>")

def _edits(raw: bytes, node: _Mutation) -> list[tuple[int, int, bytes]]:
    span = node.span
    if span is None:
        raise ValueError("内部 XML 修改节点缺少定位")
    patches = []
    opening = _start_attributes(raw, span, node.attributes)
    additions = [child for child in node.children.values() if child.span is None]
    for child in node.children.values():
        if child.span is not None:
            patches.extend(_edits(raw, child))
    if additions and opening.endswith(b"/>"):
        content = b"".join(_new_xml(child, span.namespaces) for child in sorted(additions, key=lambda child: _rank(node.tag, child.tag)))
        patches.append((span.start, span.opening_end, opening[:-2] + b">" + content + b"</" + span.qname.encode("utf-8") + b">"))
        return patches
    if opening != raw[span.start:span.opening_end]:
        patches.append((span.start, span.opening_end, opening))
    by_position: dict[int, list[_Mutation]] = {}
    for child in additions:
        if node.tag in {"p", "r"}:
            position = span.opening_end
        else:
            position = next((item.start for item in span.children if item.tag.startswith(W) and _rank(node.tag, item.tag.removeprefix(W)) > _rank(node.tag, child.tag)), span.end_start)
        by_position.setdefault(position, []).append(child)
    for position, children in by_position.items():
        patches.append((position, position, b"".join(_new_xml(child, span.namespaces) for child in sorted(children, key=lambda child: _rank(node.tag, child.tag)))))
    return patches
