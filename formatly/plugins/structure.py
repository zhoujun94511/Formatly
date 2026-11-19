"""Opt-in structural evidence checks for academic documents."""
from __future__ import annotations

from collections import Counter
import re
import unicodedata
from xml.etree.ElementTree import Element

from ..documents.academic_semantics import heading_level
from ..documents.docx_locations import DocxLocations
from ..documents.docx_scope import body_scope_roles
from ..documents.docx_semantics import (DocxParagraph, active_sections, on_off, paragraph_properties,
                                       paragraph_style, read_docx_content)
from ..documents.field_coverage import field_text_coverage
from ..domain import AuditContext, Issue, PluginResult
from ..files import NS, W, read_docx, sha256
from .citations import parse_citations
from .structure_pages import section_page_fields
from .structure_rules import STRUCTURE_LABELS, configured_structure_values, validate_structure_settings


def _normal(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


class _Checks:
    def __init__(self, locations: DocxLocations):
        self.result = PluginResult()
        self.locations = locations
        self.parents = {child: parent for parent in locations.paths for child in parent}
        document = next(node for node, path in locations.paths.items() if not path)
        self.sections = set(active_sections(document))

    def add(self, target: str, expected: object, actual: object, status: str, location: str,
            *, reason: str = "", owner: Element | None = None) -> None:
        check = {"rule_id": target, "target": target, "label": STRUCTURE_LABELS.get(target, "实际页面核对"),
                 "kind": "format", "expected": expected, "actual": actual, "status": status, "location": location}
        if reason:
            check["reason"] = reason
        if owner is not None:
            check["locator"] = self.locations.locate(owner)
        self.result.checks.append(check)
        if status in {"failed", "manual"}:
            self.result.issues.append(Issue(target, "error" if status == "failed" else "manual",
                                            reason or "文档结构与所选方案不符", location, expected, actual))


def _break_kind(paragraph: DocxParagraph, previous: DocxParagraph | None, styles: Element | None,
                sections: set[Element]) -> str | None:
    if W + "pageBreakBefore" in paragraph.property_uncertainty.get("pPr", set()):
        return None
    before = on_off(paragraph_properties(paragraph, styles), "pageBreakBefore")
    if before is None:
        return None
    if before:
        return "pageBreakBefore"
    # Only active, visible run content can prove a direct break.
    for run in paragraph.runs:
        for element in run.element.iter():
            if element.tag == W + "t" and (element.text or "").strip():
                break
            if element.tag == W + "br" and element.get(W + "type") == "page":
                return "leading-page-break"
        if run.text.strip():
            break
    if previous is None:
        return "document-start"
    tokens = [node for run in previous.runs for node in run.element.iter()
              if node.tag in {W + "t", W + "br"} and (node.tag != W + "t" or (node.text or "").strip())]
    if tokens and tokens[-1].tag == W + "br" and tokens[-1].get(W + "type") == "page":
        return "preceding-page-break"
    section = previous.element.find("w:pPr/w:sectPr", NS)
    if section is not None:
        if section not in sections:
            return None
        section_type = section.find("w:type", NS)
        kind = section_type.get(W + "val", "nextPage") if section_type is not None else "nextPage"
        if kind in {"nextPage", "oddPage", "evenPage"}:
            return "section-" + kind
        if kind not in {"continuous", "nextColumn"}:
            return None
    return "none"


def _headings(checks: _Checks, paragraphs: list[DocxParagraph], styles: Element | None, rules: dict, uncertain: bool) -> None:
    outline_uncertain = any(paragraph.numbering_reason and
                            paragraph_properties(paragraph, styles).get(W + "outlineLvl", {}).get(W + "val") == "unresolved_numbering"
                            for paragraph in paragraphs if paragraph.text.strip())
    previous_level = 0
    previous: DocxParagraph | None = None
    found = 0
    chapters = 0
    for paragraph in paragraphs:
        if not paragraph.text.strip():
            if (paragraph.element.find("w:pPr/w:sectPr", NS) is not None
                    or any(element.tag == W + "br" and element.get(W + "type") == "page"
                           for run in paragraph.runs for element in run.element.iter())):
                previous = paragraph
            continue
        level = heading_level(paragraph, styles)
        if level is not None:
            found += 1
            location = f"XML段{paragraph.index}：{paragraph.text[:60]}"
            if rules.get("hierarchy"):
                valid = level <= previous_level + 1
                checks.add("structure.headings.hierarchy", True, {"previous_level": previous_level, "level": level},
                           "manual" if uncertain or outline_uncertain else "passed" if valid else "failed", location,
                           reason=("全文存在未确认显示内容，不能确定完整标题层级" if uncertain else
                                   "编号段落的大纲级别尚未解析，不能确定完整标题层级" if outline_uncertain else
                                   "" if valid else "标题层级跳级或首个标题不是一级"),
                           owner=paragraph.element)
            if rules.get("chapter_page_break") and level == rules.get("chapter_level", 1):
                chapters += 1
                kind = _break_kind(paragraph, previous, styles, checks.sections)
                ancestor = checks.parents.get(paragraph.element)
                while ancestor is not None:
                    if ancestor.tag in {W + "tc", W + "txbxContent"}:
                        kind = None
                        break
                    ancestor = checks.parents.get(ancestor)
                checks.add("structure.headings.chapter_page_break", True, kind,
                           "manual" if uncertain or kind is None else "failed" if kind == "none" else "passed", location,
                           reason="分页设置或显示范围不明确，须在排版应用中核对" if uncertain or kind is None else "未设置可证明的章前分页" if kind == "none" else "只核对分页属性，不推断实际页面",
                           owner=paragraph.element)
            previous_level = level
        previous = paragraph
    for key, count in (("hierarchy", found), ("chapter_page_break", chapters)):
        if rules.get(key) and not count:
            checks.add("structure.headings." + key, True, None, "manual", "标题范围", reason="未找到可由大纲级别确认的对应标题")
    if outline_uncertain and rules.get("chapter_page_break") and chapters:
        checks.add("structure.headings.chapter_page_break", True, None, "manual", "标题范围",
                   reason="编号段落的大纲级别尚未解析，无法确认全部章标题的分页设置")


def _body_references(paragraphs: list[DocxParagraph], roles: dict[int, tuple[str, str]]) -> tuple[list[DocxParagraph], str]:
    """Share the same explicit body roles across citation and caption checks."""
    uncertain = any(roles.get(paragraph.index, (None, ""))[0] == "uncertain" for paragraph in paragraphs if paragraph.text.strip())
    return ([paragraph for paragraph in paragraphs if paragraph.index not in roles],
            "部分段落的正文角色尚未确认，须核对完整引用范围" if uncertain else "")


def _caption_number(text: str, label: str) -> tuple[int, ...] | None:
    text = unicodedata.normalize("NFKC", text).strip()
    pattern = re.escape(label) + r"\s*([1-9][0-9]{0,5})(?:\s*[-.]\s*([1-9][0-9]{0,5}))?(?![0-9])\s*(.+)"
    match = re.fullmatch(pattern, text, re.I)
    if match is None or match.group(3).startswith(("-", ".")):
        return None
    return tuple(int(part) for part in match.groups()[:2] if part is not None)


def _captions(checks: _Checks, paragraphs: list[DocxParagraph], styles: Element | None, rules: dict,
              uncertainty: str, reference_heading: str, roles: dict[int, tuple[str, str]]) -> None:
    targets = [key for key in ("numbering", "require_reference") if rules.get(key)]
    if not targets:
        return
    selected = rules.get("style_ids", [])
    if not selected:
        for key in targets:
            checks.add("structure.captions." + key, rules[key], None, "manual", "题注范围", reason="须明确题注样式范围，不能将正文提及当作图表题")
        return
    labels = [rules.get("figure_label", "图").strip(), rules.get("table_label", "表").strip()]
    parsed: dict[str, list[tuple[tuple[int, ...], DocxParagraph]]] = {label: [] for label in labels}
    caption_paragraphs = {paragraph.element for paragraph in paragraphs if paragraph_style(paragraph.element, styles) in selected}
    other_captions: dict[str, set[tuple[int, ...]]] = {label: set() for label in labels}
    for paragraph in paragraphs:
        if paragraph.element in caption_paragraphs or roles.get(paragraph.index, (None, ""))[0] != "caption":
            continue
        for label in labels:
            number = _caption_number(paragraph.text, label)
            if number is not None:
                other_captions[label].add(number)
    reference_paragraphs = []
    in_references = False
    for paragraph in paragraphs:
        if _normal(paragraph.text) == _normal(reference_heading):
            in_references = True
            continue
        if in_references and heading_level(paragraph, styles) is not None:
            in_references = False
        if not in_references and paragraph.element not in caption_paragraphs:
            reference_paragraphs.append(paragraph)
    body_paragraphs, body_reason = _body_references(reference_paragraphs, roles)
    ambiguous = False
    for paragraph in paragraphs:
        if paragraph.element not in caption_paragraphs or not paragraph.text.strip():
            continue
        matched = False
        for label in labels:
            number = _caption_number(paragraph.text, label)
            if number is not None:
                parsed[label].append((number, paragraph))
                matched = True
                break
        if not matched:
            ambiguous = True
            for key in targets:
                checks.add("structure.captions." + key, rules[key], paragraph.text[:100], "manual", f"XML段{paragraph.index}",
                           reason="题注标签、编号或标题不能明确解析", owner=paragraph.element)
    for label, captions in parsed.items():
        numbers = [number for number, _ in captions]
        if rules.get("numbering") and captions:
            mode = rules["numbering"]
            expected = []
            per_chapter: Counter[int] = Counter()
            start = rules.get("start", 1)
            for index, number in enumerate(numbers):
                if mode == "continuous":
                    expected.append((start + index,))
                elif len(number) == 2:
                    expected.append((number[0], start + per_chapter[number[0]]))
                    per_chapter[number[0]] += 1
                else:
                    expected.append(())
            prefixes = [number[0] for number in numbers]
            valid = numbers == expected and (mode != "chapter" or prefixes == sorted(prefixes))
            checks.add("structure.captions.numbering", mode, {"label": label, "numbers": [list(number) for number in numbers]},
                       "manual" if uncertainty or ambiguous else "passed" if valid else "failed", label + "题注编号",
                       reason=uncertainty or ("题注存在未解析项，不能确认完整编号" if ambiguous else "" if valid else "题注编号重复、跳号或与编号方式不符"))
            if mode == "chapter":
                checks.add("structure.captions.chapter_mapping", None, None, "manual", label + "题注章号",
                           reason="按题注前缀核对各组序列；题注前缀与实际章号的对应仍需人工核对")
        if rules.get("require_reference"):
            prose = unicodedata.normalize("NFKC", "\n".join(paragraph.text for paragraph in body_paragraphs))
            range_pattern = (re.escape(label) + r"\s*[1-9][0-9]{0,5}(?:\s*[-.]\s*[1-9][0-9]{0,5})?"
                             + r"\s*(?:(?:[~～–—]|至|到)\s*(?:" + re.escape(label) + r"\s*)?[0-9]|[、,，]\s*[0-9])")
            range_reason = "图表引用使用范围或省略写法，须人工核对" if re.search(range_pattern, prose, re.I) else ""
            for number, paragraph in captions:
                number_pattern = r"\s*[-.]\s*".join(str(part) for part in number)
                boundary = r"(?<![A-Za-z0-9_])" if label[0].isascii() and label[0].isalnum() else ""
                pattern = boundary + re.escape(label) + r"\s*" + number_pattern + r"(?![0-9]|\s*[-.]\s*[0-9])"
                match = re.search(pattern, prose, re.I)
                found = match is not None
                reason = uncertainty or body_reason or range_reason
                checks.add("structure.captions.require_reference", True, {"label": label, "number": list(number), "found": found},
                           "manual" if reason or ambiguous else "passed" if found else "failed", f"XML段{paragraph.index}：{paragraph.text[:60]}",
                           reason=reason or ("题注存在未解析项，须核对完整引用" if ambiguous else "" if found else "未找到该图表的明确正文引用"), owner=paragraph.element)
            boundary = r"(?<![A-Za-z0-9_])" if label[0].isascii() and label[0].isalnum() else ""
            reference_pattern = (boundary + re.escape(label) + r"\s*([1-9][0-9]{0,5})(?:\s*[-.]\s*([1-9][0-9]{0,5}))?(?![0-9])")
            # Other explicit captions can prove existence without joining this
            # rule's numbering sequence or satisfying its body references.
            known = set(numbers) | other_captions[label]
            for paragraph in body_paragraphs:
                mentioned = {tuple(int(part) for part in match.groups() if part is not None)
                             for match in re.finditer(reference_pattern, unicodedata.normalize("NFKC", paragraph.text), re.I)}
                for number in sorted(mentioned - known):
                    reason = uncertainty or body_reason or range_reason or ("题注存在未解析项，须核对完整引用" if ambiguous else "")
                    if not any(parsed.values()):
                        reason = reason or "没有可核验题注，不能确定完整引用关系"
                    checks.add("structure.captions.require_reference", True,
                               {"label": label, "number": list(number), "found_caption": False},
                               "manual" if reason else "failed", f"XML段{paragraph.index}：{paragraph.text[:60]}",
                               reason=reason or "正文引用没有对应的已确认题注", owner=paragraph.element)
    if not any(parsed.values()) and not ambiguous:
        for key in targets:
            checks.add("structure.captions." + key, rules[key], None, "manual", "题注范围", reason="没有匹配已确认样式的可核验题注")


def _references(checks: _Checks, paragraphs: list[DocxParagraph], styles: Element | None, rules: dict,
                uncertainty: str, roles: dict[int, tuple[str, str]]) -> None:
    targets = [key for key in ("correspondence", "require_all_cited") if rules.get(key)]
    if not targets:
        return
    indices = [index for index, paragraph in enumerate(paragraphs) if _normal(paragraph.text) == _normal(rules.get("heading", "参考文献"))]
    if len(indices) != 1:
        for key in targets:
            checks.add("structure.references." + key, True, None, "manual", "参考文献范围", reason="参考文献章节不存在或不唯一，不能确定正文与条目范围")
        return
    boundary = indices[0]
    entries = []
    ambiguous = False
    for paragraph in paragraphs[boundary + 1:]:
        if heading_level(paragraph, styles) is not None:
            break
        if not paragraph.text.strip():
            continue
        match = re.match(r"^\s*\[([1-9][0-9]{0,5})]\s*\S", unicodedata.normalize("NFKC", paragraph.text))
        if match is None:
            ambiguous = True
        else:
            entries.append(int(match.group(1)))
    body_paragraphs, body_reason = _body_references(paragraphs[:boundary], roles)
    citations = parse_citations(paragraph.text for paragraph in body_paragraphs)
    cited, listed = set(citations.numbers), set(entries)
    duplicates = sorted(number for number, count in Counter(entries).items() if count > 1)
    reason = uncertainty or body_reason or ("；".join(citations.warnings)) or ("参考文献包含未能明确解析的条目或续段" if ambiguous else "")
    if not entries:
        reason = reason or "未找到明确的数字编号参考文献条目"
    actual = {"citations": sorted(cited), "entries": entries, "missing_entries": sorted(cited - listed),
              "uncited_entries": sorted(listed - cited), "duplicate_entries": duplicates}
    for key in targets:
        valid = not (cited - listed) and not duplicates if key == "correspondence" else not (listed - cited) and not duplicates
        checks.add("structure.references." + key, True, actual, "manual" if reason else "passed" if valid else "failed", "正文与参考文献",
                   reason=reason or ("" if valid else "引用缺少对应条目、条目重复或存在未引用条目"))


class AcademicStructurePlugin:
    id = "academic-structure"
    name = "论文与报告结构"
    description = "按显式配置核对标题、分页设置、图表题引用、文献对应和页码域；不推断实际分页。"
    settings_keys = ("structure",)
    formats = ("docx", "pdf", "txt", "md", "json")
    kinds = ("thesis", "intern", "certificate")

    @staticmethod
    def probe() -> tuple[bool, str]:
        return True, "内置结构检查可用；DOCX结构属性按可读取证据核验"

    validate_settings = staticmethod(validate_structure_settings)

    @staticmethod
    def run(context: AuditContext) -> PluginResult:
        configured = dict(configured_structure_values(context.settings))
        if not configured:
            return PluginResult(checks=[{"rule_id": "structure.settings", "target": "structure.settings", "status": "not_checked",
                                         "reason": "尚未配置结构要求"}])
        if context.input_path.suffix.lower() != ".docx":
            return PluginResult(checks=[{"rule_id": target, "target": target, "status": "unsupported", "expected": expected,
                                         "actual": None, "reason": "该结构规则需明确的DOCX样式、域或分节信息；当前格式不推断这些属性"}
                                        for target, expected in configured.items()])
        package = context.cache.get("docx") or read_docx(context.input_path)
        context.cache["docx"] = package
        content = package.get("content") or read_docx_content(package["document"], package["styles"], numbering=package.get("numbering"),
                                                              styles_reason=package.get("styles_reason", ""))
        package["content"] = content
        checks = _Checks(DocxLocations(package["document"], sha256(context.input_path)))
        rules = context.settings["structure"]
        coverage = field_text_coverage({"format": "docx", "complete": True, "requires_review": content.requires_review,
                                        "text": "\n".join(paragraph.text for paragraph in content.paragraphs),
                                        "entries": [{"method": "text"}], "docx": package})
        # Header/footer text is deliberately outside body-reference scope.
        reasons = [reason for reason in coverage["reasons"] if reason != "docx_unread_parts"]
        if any(part in package["parts"] for part in ("word/footnotes.xml", "word/endnotes.xml")):
            reasons.append("docx_notes_outside_body_scope")
        uncertainty = "正文含未确认的显示内容，不能证明完整编号或引用关系" if reasons else ""
        roles = body_scope_roles(package["document"], package["styles"], content.paragraphs, exclude_containers=True)
        _headings(checks, content.paragraphs, package["styles"], rules.get("headings", {}), content.requires_review)
        _captions(checks, content.paragraphs, package["styles"], rules.get("captions", {}), uncertainty,
                  rules.get("references", {}).get("heading", "参考文献"), roles)
        _references(checks, content.paragraphs, package["styles"], rules.get("references", {}), uncertainty, roles)
        page_rules = rules.get("page_numbers", {})
        if any("structure.page_numbers." + key in configured for key in ("require_field", "format", "start")):
            sections = active_sections(package["document"])
            fields = section_page_fields(context.input_path, sections, package["styles"], styles_reason=package.get("styles_reason", ""))
            selected = page_rules.get("section_indices", list(range(1, len(sections) + 1)))
            if not sections and not selected:
                for key in ("require_field", "format", "start"):
                    target = "structure.page_numbers." + key
                    if target in configured:
                        checks.add(target, configured[target], None, "manual", "分节范围", reason="没有有效分节设置")
            for index in selected:
                if index > len(sections):
                    for key in ("require_field", "format", "start"):
                        target = "structure.page_numbers." + key
                        if target in configured:
                            checks.add(target, configured[target], None, "manual", f"第{index}节", reason="所选分节不存在")
                            checks.result.checks[-1]["section_index"] = index
                    continue
                section = sections[index - 1]
                if page_rules.get("require_field"):
                    found, reason, parts = fields[index - 1]
                    checks.add("structure.page_numbers.require_field", True, {"found": found, "parts": parts},
                               "manual" if reason else "passed" if found else "failed", f"第{index}节", reason=reason or (
                               "仅核对默认／奇偶页眉页脚PAGE域；首页显示及实际页码另行核对" if found else "未找到适用于默认／奇偶页的PAGE域"), owner=section)
                    checks.result.checks[-1]["section_index"] = index
                numbering = section.find("w:pgNumType", NS)
                for key, attr in (("format", "fmt"), ("start", "start")):
                    target = "structure.page_numbers." + key
                    if target not in configured:
                        continue
                    value = numbering.get(W + attr) if numbering is not None else None
                    reason = ""
                    if key == "start":
                        if value is None:
                            # Word numbers the first section from 1 when start is omitted.
                            actual: object = 1 if index == 1 else "continue"
                        elif re.fullmatch(r"[1-9][0-9]{0,5}", value):
                            actual = int(value)
                        else:
                            actual, reason = None, "页码起始属性无效"
                    else:
                        actual = value
                        if value is None:
                            reason = "页码格式未显式设置，不推断分节继承结果"
                    checks.add(target, configured[target], actual, "manual" if reason else "passed" if actual == configured[target] else "failed",
                               f"第{index}节", reason=reason, owner=section)
                    checks.result.checks[-1]["section_index"] = index
        if rules.get("headings", {}).get("chapter_page_break") or page_rules:
            checks.add("structure.layout.visual", None, None, "manual", "实际页面",
                       reason="域和分页属性不能证明实际分页、首页页码、页码显示或目录一致性；须结合Word/WPS页面核对")
        checks.result.evidence = {"configured_targets": sorted(configured), "paragraphs": len(content.paragraphs),
                                  "body_scope_reasons": reasons, "content_warnings": content.warnings}
        return checks.result
