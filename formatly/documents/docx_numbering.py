"""Bounded numbering definitions and paragraph-level formatting evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from ..files import NS, W
from .ooxml import parse_on_off, read_related_xml

UNRESOLVED_NUMBERING = "unresolved_numbering"
_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"


def _identity(raw: str | None, maximum: int = 2_147_483_647) -> str | None:
    if raw is None or len(raw) > 12 or re.fullmatch(r"\+?[0-9]+", raw) is None:
        return None
    value = int(raw)
    return str(value) if value <= maximum else None


def _single(parent: Element, name: str) -> Element | None:
    nodes = parent.findall("w:" + name, NS)
    if len(nodes) > 1:
        raise ValueError("编号定义包含重复属性")
    return nodes[0] if nodes else None


@dataclass(frozen=True)
class NumberingResolution:
    properties: Element | None = None
    reason: str = ""


@dataclass
class NumberingContext:
    """One package's related numbering part; no process-wide document state."""

    root: Element | None = None
    reason: str = "缺少可读取的编号定义部件"
    instances: dict[str, list[Element]] = field(default_factory=dict)
    abstracts: dict[str, list[Element]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.root is None:
            return
        for tag, attribute, index in (("num", "numId", self.instances), ("abstractNum", "abstractNumId", self.abstracts)):
            for node in self.root.findall("w:" + tag, NS):
                identity = _identity(node.get(W + attribute))
                if identity is not None:
                    index.setdefault(identity, []).append(node)

    def _instance(self, identity: str) -> Element:
        nodes = self.instances.get(identity, [])
        if len(nodes) != 1:
            raise ValueError("编号实例不存在或不唯一")
        return nodes[0]

    def _abstract(self, instance: Element, styles: Element | None, seen: set[str]) -> tuple[Element, list[Element]]:
        reference = _single(instance, "abstractNumId")
        identity = _identity(reference.get(W + "val")) if reference is not None else None
        nodes = self.abstracts.get(identity or "", [])
        if identity is None or len(nodes) != 1 or identity in seen:
            raise ValueError("抽象编号定义不存在、不唯一或存在循环链接")
        seen.add(identity)
        abstract = nodes[0]
        link = _single(abstract, "numStyleLink")
        if link is None:
            return abstract, [instance]
        if len(seen) > 16 or styles is None:
            raise ValueError("编号样式链接无法解析")
        identity = link.get(W + "val")
        linked = [node for node in styles.findall("w:style", NS)
                  if node.get(W + "styleId") == identity and node.get(W + "type") == "numbering"]
        if len(linked) != 1:
            raise ValueError("编号样式链接不存在或不唯一")
        props = _single(linked[0], "pPr")
        number = _single(props, "numPr") if props is not None else None
        number_id = _single(number, "numId") if number is not None else None
        value = _identity(number_id.get(W + "val")) if number_id is not None else None
        if value is None or value == "0":
            raise ValueError("编号样式缺少有效编号实例")
        abstract, instances = self._abstract(self._instance(value), styles, seen)
        return abstract, [*instances, instance]

    def resolve(self, number_id: str, level: str, styles: Element | None,
                style_link: str | None = None, style_level: bool = False,
                direct_level: bool = False) -> NumberingResolution:
        if self.root is None:
            return NumberingResolution(reason=self.reason)
        try:
            instance = self._instance(number_id)
            abstract, instances = self._abstract(instance, styles, set())
            levels: dict[str, list[Element]] = {}
            for node in abstract.findall("w:lvl", NS):
                identity = _identity(node.get(W + "ilvl"), 8)
                if identity is not None:
                    levels.setdefault(identity, []).append(node)
            for source in instances:
                overrides: dict[str, list[Element]] = {}
                for node in source.findall("w:lvlOverride", NS):
                    identity = _identity(node.get(W + "ilvl"), 8)
                    if identity is not None:
                        overrides.setdefault(identity, []).append(node)
                for identity, nodes in overrides.items():
                    if len(nodes) != 1 or len(nodes[0].findall("w:lvl", NS)) > 1:
                        levels[identity] = []
                        continue
                    replacement = nodes[0].find("w:lvl", NS)
                    if replacement is not None:
                        # A full override replaces the complete level, including
                        # omission of a base-level indentation or style link.
                        levels[identity] = [replacement] if _identity(replacement.get(W + "ilvl"), 8) == identity else []
            # A paragraph's own ilvl selects the level. The style link only
            # supplies a level when the paragraph did not write one directly.
            if style_link is not None and not direct_level:
                linked = []
                for nodes in levels.values():
                    for node in nodes:
                        link = _single(node, "pStyle")
                        if link is not None and link.get(W + "val") == style_link:
                            linked.append(node)
                if len(linked) != 1:
                    raise ValueError("段落样式没有唯一对应的编号级别")
                linked_level = _identity(linked[0].get(W + "ilvl"), 8)
                if linked_level is None or (style_level and linked_level != level):
                    # Word and the standard differ for a style's explicit ilvl.
                    raise ValueError("段落样式的编号级别与级别样式链接不一致")
                level = linked_level
            selected = levels.get(level, [])
            if len(selected) != 1:
                raise ValueError("编号级别不存在或不唯一")
            chosen = selected[0]
            properties = _single(chosen, "pPr")
            if properties is not None:
                tags = [node.tag for node in properties]
                if len(set(tags)) != len(tags) or properties.find("w:numPr", NS) is not None:
                    raise ValueError("编号级段落属性重复或包含嵌套编号")
            return NumberingResolution(properties)
        except ValueError as exc:
            return NumberingResolution(reason=str(exc))


def read_numbering(package: ZipFile, types: Element) -> NumberingContext:
    """Read only the internally related, correctly typed and bounded XML part."""
    part = read_related_xml(package, types, _TYPE, W + "numbering", _CONTENT_TYPE, "编号")
    return NumberingContext(part.root, part.reason)


def paragraph_numbering(paragraph: Element, styles: Element | None,
                        context: NumberingContext | None) -> NumberingResolution:
    """Resolve direct/inherited numPr, including an explicit numId=0 reset."""
    layers: list[tuple[str | None, Element]] = []
    style_id = paragraph.find("w:pPr/w:pStyle", NS)
    identity = style_id.get(W + "val") if style_id is not None else None
    style_ambiguity = False
    if styles is not None:
        declared = styles.findall("w:style", NS)
        indexed = {node.get(W + "styleId"): node for node in declared}
        defaults = styles.find("w:docDefaults/w:pPrDefault/w:pPr", NS)
        if defaults is not None:
            layers.append((None, defaults))
        if identity is None:
            identity = next((node.get(W + "styleId") for node in indexed.values()
                             if node.get(W + "type") == "paragraph" and parse_on_off(node.get(W + "default"), default=False) is True), "Normal")
        chain, seen = [], set()
        while identity in indexed and identity not in seen:
            seen.add(identity)
            if sum(node.get(W + "styleId") == identity for node in declared) != 1:
                style_ambiguity = True
            node = indexed[identity]
            props = node.find("w:pPr", NS)
            if props is not None:
                chain.append((identity, props))
            parent = node.find("w:basedOn", NS)
            identity = parent.get(W + "val") if parent is not None else None
        style_ambiguity |= identity is not None
        layers.extend(reversed(chain))
    direct = paragraph.find("w:pPr", NS)
    if direct is not None:
        layers.append((None, direct))
    values: dict[str, str | None] = {}
    number_style = None
    style_level = False
    direct_level = False
    ambiguous = False
    has_numbering = False
    for owner, props in layers:
        numbers = props.findall("w:numPr", NS)
        has_numbering |= bool(numbers)
        if len(numbers) > 1:
            ambiguous = True
        for number in numbers:
            for name in ("numId", "ilvl"):
                children = number.findall("w:" + name, NS)
                if len(children) > 1:
                    ambiguous = True
                if children:
                    values[name] = children[-1].get(W + "val")
                    if name == "numId":
                        number_style = owner
                    else:
                        style_level = owner is not None
                        direct_level = owner is None
    if not has_numbering:
        return NumberingResolution()
    number_id = _identity(values.get("numId"))
    if number_id == "0" and not ambiguous:
        return NumberingResolution()
    level = _identity(values.get("ilvl", "0"), 8)
    if ambiguous or style_ambiguity or number_id is None or level is None:
        return NumberingResolution(reason="段落编号实例或级别缺失、无效或重复")
    return (context or NumberingContext()).resolve(
        number_id, level, styles, number_style, style_level, direct_level)
