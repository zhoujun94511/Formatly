"""Conservative Markdown text scope for heading, field and citation checks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HTML = re.compile(r"<\s*[A-Za-z/!?]")


@dataclass
class MarkdownText:
    lines: list[tuple[int, str]] = field(default_factory=list)
    requires_review: bool = False

    @property
    def entries(self) -> list[dict]:
        return [{"text": text, "location": f"Markdown第{number}行", "method": "text"}
                for number, text in self.lines]


def heading_text(text: str) -> str:
    """Remove actual ATX delimiters while retaining ordinary leading hashes."""
    match = re.match(r"^ {0,3}#{1,6}(?:[ \t]+|$)(.*)$", text)
    if match:
        text = re.sub(r"[ \t]+#+[ \t]*$", "", match[1])
    return "".join(text.split()).casefold()


def visible_text(text: str) -> MarkdownText:
    """Exclude definite code/comments without interpreting the full language.

    Line numbers refer to the unchanged source. Unsupported HTML, nested
    blocks and unfinished delimiters prevent a conclusive absence finding.
    The original Markdown remains the extraction artifact; consumers share
    these visible entries and their unchanged source line numbers.
    """
    result = MarkdownText()
    fence_character, fence_length = "", 0
    comment = False
    for number, raw_line in enumerate(text.splitlines(), 1):
        if fence_character:
            if re.fullmatch(r" {0,3}" + re.escape(fence_character) + "{" + str(fence_length) + r",}[ \t]*", raw_line):
                fence_character, fence_length = "", 0
            continue

        # Comments may span lines, begin after visible text or end before it.
        # Fence-looking content inside a comment never opens a code block.
        pieces, position = [], 0
        while position < len(raw_line):
            if comment:
                end = raw_line.find("-->", position)
                if end < 0:
                    break
                comment, position = False, end + 3
            else:
                start = raw_line.find("<!--", position)
                if start < 0:
                    pieces.append(raw_line[position:])
                    break
                pieces.append(raw_line[position:start])
                comment, position = True, start + 4
        line = "".join(pieces)
        opening = _FENCE.match(line)
        if opening:
            marker, info = opening.groups()
            if marker[0] == "`" and "`" in info:
                result.requires_review = True
                continue
            fence_character, fence_length = marker[0], len(marker)
            continue
        if not line.strip():
            continue
        if line.startswith(("    ", "\t")):
            # Indented blocks can depend on the enclosing paragraph/list.
            result.requires_review = True
            continue
        if _HTML.search(line) or re.match(r"^ {0,3}(?:>|[-+*][ \t]|[0-9]+[.)][ \t])", line):
            result.requires_review = True
        atx = re.match(r"^ {0,3}#{1,6}(?:[ \t]+|$)(.*)$", line)
        if atx and re.search(r"[`*_\\\[\]]|&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z]+);", atx[1]):
            # Inline formatting is outside this lexical scope. Its visible
            # title must not be declared missing merely from the raw markup.
            result.requires_review = True
        result.lines.append((number, line.strip()))
    result.requires_review = result.requires_review or comment or bool(fence_character)
    return result
