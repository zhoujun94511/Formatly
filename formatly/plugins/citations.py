"""Bounded citation parsing and shared whole-document evidence requirements."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from ..documents.field_coverage import field_text_coverage


@dataclass
class CitationSequence:
    numbers: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_citations(texts, *, max_numbers=10_000, max_range=1_000) -> CitationSequence:
    """Accept numeric groups/ranges; never silently omit a numeric bracket.

    Expansion and integer conversion are bounded independently of user input.
    Non-numeric brackets remain ordinary prose. Unclosed numeric brackets and
    unsupported numeric syntax require review instead of proving a pass.
    """
    result = CitationSequence()

    def warn(reason):
        if reason not in result.warnings:
            result.warnings.append(reason)

    for text in texts:
        text = unicodedata.normalize("NFKC", text)
        for match in re.finditer(r"\[([^\[\]\n]*)(]|(?=\[|\n|$))", text):
            token, closing = match.groups()
            if not any(character.isnumeric() for character in token):
                continue
            if not closing or len(token) > 128:
                warn("存在未闭合或过长的数字引用，须核对引用写法")
                continue
            if re.fullmatch(r"\s*[0-9]+(?:\s*(?:[,，、;；]|[-–—~～])\s*[0-9]+)*\s*", token) is None:
                warn("存在无法解释的数字引用写法，须核对全文引用")
                continue
            numbers = []
            for part in re.split(r"[,，、;；]", token):
                bounds = re.split(r"[-–—~～]", part)
                if len(bounds) > 2 or any(len(value.strip()) > 7 for value in bounds):
                    warn("引用范围或编号超过解析预算，须核对全文引用")
                    numbers = []
                    break
                start, end = int(bounds[0]), int(bounds[-1])
                if not 1 <= start <= end <= 1_000_000 or end - start >= max_range:
                    warn("引用范围或编号无效，须核对全文引用")
                    numbers = []
                    break
                if len(result.numbers) + len(numbers) + end - start + 1 > max_numbers:
                    warn("引用数量超过解析预算，须核对全文引用")
                    return result
                numbers.extend(range(start, end + 1))
            result.numbers.extend(numbers)
    return result


def body_citation_texts(texts, *, heading_found: bool) -> list[str]:
    """Keep in-text citations. A missing heading cannot use bibliography entries."""
    selected = list(texts)
    if heading_found:
        return selected
    body = []
    for text in selected:
        # Fullwidth brackets and spaces inside the marker are still a bibliography entry.
        normalized = unicodedata.normalize("NFKC", text)
        remainder = re.sub(r"^\s*\[\s*\d+\s*]", "", normalized, count=1)
        if remainder != normalized and not re.search(r"\[\s*\d", remainder):
            continue
        body.append(text)
    return body


def citation_review_reason(document: dict, citations: CitationSequence) -> str:
    """A global result requires complete native text and complete parsing."""
    reasons = field_text_coverage(document)["reasons"]
    if document.get("format") == "json":
        # The JSON reader walks every string value. Citation checks operate on
        # those text values; they do not assert that a labelled form contains
        # every required field, which needs an explicit fields-table contract.
        reasons = [reason for reason in reasons if reason != "json_text_scope_undeclared"]
    if reasons:
        return "全文未完整读取或包含尚未核对的 OCR/辅助文字，不能确定全文引用结论"
    if citations.warnings:
        return "；".join(citations.warnings)
    if not citations.numbers:
        return "未提取到正文参考文献引用"
    return ""
