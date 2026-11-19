"""Explicit measurements and bounded subject context in school instructions."""
from __future__ import annotations

import re
import unicodedata

RuleValue = tuple[str, str | float | int, str]
HeadingValue = tuple[str, str, str]
_NON_BODY = r"摘要|Abstract|关键词|目录|章节标题|标题|题目|页眉|页脚|页码|图题|图注|表题|表内|表格|参考文献|附录|致谢|脚注|注释|封面"
# Bind suffixes and anchors to the complete subject choice.
_NON_BODY_CHOICE = rf"(?:{_NON_BODY})"
_SUBJECT = re.compile(r"其余文字|其余正文|其他正文|正文|" + _NON_BODY, re.I)
_GENERAL_HEADING = re.compile(r"编辑设置|全文(?:格式|排版|设置|文字规范)|通用(?:格式|排版|要求)")
_SIZE_POINTS = {"初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18,
                "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
                "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5}
_SIZE = re.compile("|".join(_SIZE_POINTS) + r"|(?P<points>\d+(?:\.\d+)?)\s*(?:磅|pt\b)", re.I)
_CHINESE_FONT = r"宋体|黑体|仿宋(?:_GB2312)?|楷体(?:_GB2312)?"
_LATIN_FONT = r"Times\s*New\s*Roman|新罗马体?|Arial|Calibri"
_OTHER_MEASUREMENT = r"行间?距|多倍行距|固定(?:值|行距)|段前|段后|段间距|字间距|字距|行高|缩进|边距|装订线"
_SIZE_SUBJECT = re.compile(r"(?P<font>字号|字体|字型|文字大小|正文\s*(?:使用|采用|用)|"
                           + _CHINESE_FONT + "|" + _LATIN_FONT + r")|(?P<other>" + _OTHER_MEASUREMENT + ")", re.I)
_PAPER_CONTEXT = re.compile(r"(?:纸张|纸型|纸型大小|页面).{0,12}A4(?![A-Za-z0-9])|"
                            r"(?<![A-Za-z0-9])A4.{0,12}(?:纸|页面)", re.I)
_PAPER_UNCERTAIN = re.compile(r"不得|不能|不应|禁止|不使用|不采用|不用|无需|不必|不要求|非\s*A4|"
                              r"建议|推荐|例如|示例|样例|任选|可选|允许|可以|可[采使选用横纵竖]|或者?|[、/]|"
                              r"如需|如有|若|当|根据|视|部分|附录|附件|封面|仅|除|其余|其他|[不非][横纵竖]", re.I)
_SIDE = r"[上下左右](?:\s*[、，,和及/]?\s*[上下左右])*"
_MARGIN = re.compile(rf"(?P<sides>{_SIDE})\s*侧?\s*(?P<edge>页?边距)?\s*"
                     r"[均各]?\s*(?:设置为|设为|[为是:：=])?\s*"
                     r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>毫米|厘米|mm|cm)", re.I)
_EXAMPLE = re.compile(r"示例|样例|举例|例如|比如|范例|示范|仅供参考|可参考|正文中(?:提及|讨论|描述)")
_OPTIONAL = re.compile(r"可选|非必[选需须备]|非强制|选填|任选|有则|必要时|视需要|如有|若有|"
                       r"(?:可以?不|不必|无需)(?:设置|包含|列出|单列|提供|编写|提交|设立|撰写)")
_NEGATED_REQUIREMENT = re.compile(r"无需|不必|不要求|不应|不得|不能|禁止|不需要|可以不|可不|非必[备需须]|非强制")
_QUOTED_HEADING = re.compile(r'[“「『"]([^”」』"\n]{1,80})[”」』"]')
_LIST_NUMBER = re.compile(r"\(\s*(?:\d{1,3}|[一二三四五六七八九十]+)\s*\)|"
                          r"(?:^|\s)[1-9]\d{0,2}[、.]\s*")
MAX_HEADING_EVIDENCE = 128
MAX_HEADING_ITEMS = 32
MAX_HEADING_LINE = 1800


def _heading_items(value: str, *, composition: bool = False) -> list[str]:
    numbered = _LIST_NUMBER.split(value)
    separators = r"[、，,；;]"
    if composition and (value.count("-") >= 2 or re.search(r"[—–→]", value)):
        separators = r"[、，,；;—–→-]"
    items = numbered if len(numbered) > 1 else re.split(separators, value)
    return [item.strip(" \t\r\n、，,；;。:：") for item in items if item.strip(" \t\r\n、，,；;。:：")][:MAX_HEADING_ITEMS]


def _literal_heading(value: str) -> str | None:
    name = value.strip(" \t“”「」『』\"")
    name = re.sub(r"\s*(?:等(?:章节|标题|部分)|章节|标题)$", "", name).strip()
    if (not 1 <= len(name) <= 80 or _OPTIONAL.search(name)
            or re.search(r"[。:：;；、，,（）()及与或和]", name)
            or re.search(r"必须|应当|包括|包含|使用|采用|设置|字号|字体|行距|页码|格式|组成|"
                         r"(?:正文|标题|章节|文字)[用为需应]|宋体|黑体|楷体|仿宋", name)):
        return None
    return name


def _quoted_heading_list(value: str) -> list[str]:
    """Do not collect a second instruction's quoted font or example text."""
    matches = list(_QUOTED_HEADING.finditer(value))[:MAX_HEADING_ITEMS]
    if not matches:
        return []
    selected = [matches[0][1]]
    for previous, current in zip(matches, matches[1:]):
        between = value[previous.end():current.start()]
        if not re.fullmatch(r"[\s、，,及和与]*(?:(?:标题|章节)[\s、，,及和与]*)?", between):
            break
        selected.append(current[1])
    return selected


def _optional_heading(name: str, lines: list[tuple[str, str]]) -> bool:
    for _, line in lines:
        if len(line) > MAX_HEADING_LINE or _EXAMPLE.search(line):
            continue
        for clause in re.split(r"[。；;]", line):
            for match in re.finditer(re.escape(name), clause):
                before, after = clause[:match.start()], clause[match.end():]
                if re.match(r"[中内]|的?内容|的?正文", after.lstrip("”」』\"")):
                    continue
                # Optional content within a section is not an optional section.
                suffix = re.split(r"[，,、]", after, maxsplit=1)[0]
                prefix = re.split(r"[，,、]", before)[-1]
                if _OPTIONAL.search(suffix[:16]) or re.search(
                        r"(?:可以?不|不必|无需)(?:设置|包含|列出|单列|提供|编写|提交|设立|撰写)\s*[“「『\"]?$", prefix):
                    return True
    return False


def _part_supports_heading(part: str, name: str) -> bool:
    compact = "".join(part.split()).strip("“”「」『』\"")
    if re.search(r"或|任选|可选|不含|不包括|无需|不需要", compact):
        return False
    return any(re.fullmatch(r"(?:中外\(英\)文|中外文|中英文|中文|英文|外文)?" + re.escape(name),
                            item.strip("“”「」『』\""))
               for item in re.split(r"[及与和]", compact))


def required_heading_values(lines: list[tuple[str, str]]) -> dict[int, list[HeadingValue]]:
    """Match required composition with an explicit, literal heading name.

    A document part is not necessarily a standalone title. Composition lists
    therefore need a second naming statement; only explicit title/section
    requirement lists can prescribe the name directly. Optional and example
    clauses never become automatic requirements.
    """
    parts: list[tuple[str, int]] = []
    direct: list[tuple[str, int, int]] = []
    named: list[tuple[str, int]] = []
    for index, (_, raw) in enumerate(lines):
        if len(raw) > MAX_HEADING_LINE or _EXAMPLE.search(raw):
            continue
        normalized = unicodedata.normalize("NFKC", raw)
        for clause in re.split(r"[。；;]", normalized):
            if _NEGATED_REQUIREMENT.search(clause):
                continue
            requirement = re.search(r"(?:必须|应当|应|须|需要|需)(?:分别|完整|至少|同时|依次)?"
                                    r"(?:包含|包括|设置|设有|有)|必备标题|必需标题", clause)
            requested = clause[requirement.end():] if requirement else ""
            quoted = list(_QUOTED_HEADING.finditer(requested))[:MAX_HEADING_ITEMS]
            names = _quoted_heading_list(requested)
            # A later sentence fragment about heading fonts does not turn a
            # required piece of content into a prescribed standalone heading.
            declaration = re.split(r"[，,]", clause[:requirement.end()])[-1] if requirement else ""
            label_prefix = requested[:quoted[0].start()] if quoted else requested.split(":", 1)[0]
            label_suffix = requested[quoted[len(names) - 1].end():] if names else ""
            explicit = requirement is not None and bool(
                re.search(r"标题|章节", declaration + label_prefix)
                or re.match(r"\s*(?:[两二三四\d]+个)?(?:独立)?(?:标题|章节)", label_suffix))
            if requirement and re.search(r"建议|推荐|可以?|允许|是否", clause[:requirement.start()]):
                explicit = False
            composition = re.search(
                r"(?:文稿|论文(?:\([^)]*\))?|报告|文档).{0,20}(?:按.{0,12}顺序装订|依次装订|包括以下部分|"
                r"由以下[几各]?部分组成)(?:\([^)]{0,40}\))?\s*[:：]", clause)
            by_parts = re.search(r"(?:文稿|论文(?:\([^)]*\))?|报告|文档)由(.{1,1000})组成", clause)
            composition_match = composition if composition is not None else by_parts
            if composition_match is not None:
                if re.search(r"可以?|建议|推荐|正文中|摘要内容", clause[:composition_match.end()]):
                    continue
                value = clause[composition.end():] if composition is not None else composition_match[1]
                parts.extend((item, index) for item in _heading_items(value, composition=True) if not _OPTIONAL.search(item))
                parts = parts[:MAX_HEADING_EVIDENCE]
            if explicit:
                # The quote contents are the required labels, never an example.
                tail = re.split(r"[:：]", requested, maxsplit=1)
                if not names and len(tail) == 2:
                    names = _heading_items(tail[1])
                for item in names:
                    if name := _literal_heading(item):
                        direct.append((name, index, index))
                # A required list may continue on separately numbered lines.
                if not names and len(tail) == 2 and not tail[1].strip():
                    for next_index in range(index + 1, min(len(lines), index + MAX_HEADING_ITEMS + 1)):
                        continuation = unicodedata.normalize("NFKC", lines[next_index][1])
                        if not _LIST_NUMBER.match(continuation) or _EXAMPLE.search(continuation):
                            break
                        for item in _heading_items(continuation):
                            if name := _literal_heading(item):
                                direct.append((name, next_index, index))
            # Naming evidence alone does not prove that the section is required.
            for match in _QUOTED_HEADING.finditer(clause):
                before, after = clause[:match.start()], clause[match.end():]
                title_name = bool(re.search(r"(?:章节)?标题\s*(?:为|是|用|写为|写作|采用)?\s*$", before)
                                  or (re.match(r"(?:两|二|三|四|\d)字", after)
                                      and re.search(r"单独(?:设页|成页)|另起一页|标题|居中", clause)
                                      and not re.search(r"正文[中内]|作为.{0,8}例", clause)))
                if title_name and (name := _literal_heading(match[1])):
                    named.append((name, index))
        direct = direct[:MAX_HEADING_EVIDENCE]
        named = named[:MAX_HEADING_EVIDENCE]
    for name, index in named:
        for item, introduction in parts:
            # A conjunction denotes a combined part, not multiple prescribed
            # labels. An independently stated title can disambiguate its name.
            if _part_supports_heading(item, name):
                direct.append((name, index, introduction))
                break
    result: dict[int, list[HeadingValue]] = {}
    seen: set[str] = set()
    for name, index, introduction in direct[:MAX_HEADING_EVIDENCE]:
        if name in seen or _optional_heading(name, lines):
            continue
        seen.add(name)
        locator, raw = lines[index]
        if introduction != index:
            intro_locator, intro_text = lines[introduction]
            combined = f"{locator}（组成要求：{intro_locator}）"
            if len(combined) <= 300:
                locator = combined
            excerpt = intro_text[:950] + "\n" + raw[:950]
        else:
            excerpt = raw
        result.setdefault(index, []).append((name, locator, excerpt))
    return result


def margin_values(line: str, *, furniture: bool = False) -> list[RuleValue]:
    """Read grouped page margins without treating header/footer offsets as margins."""
    values: list[RuleValue] = []
    normalized = unicodedata.normalize("NFKC", line)
    for clause in re.split(r"[。；;]", normalized):
        # A page-margin clause can precede a header clause on the same line.
        visible = re.split(r"页眉|页脚", clause, maxsplit=1)[0]
        if furniture and not re.search(r"(?<![上下左右])页边距|页面设置|纸张边距", visible):
            continue
        for piece in re.split(r"[，,]", visible):
            if not _MARGIN.search(piece):
                continue
            if re.search(r"不小于|不大于|至少|至多|不得|不应|不能|禁止|不超过|不少于", piece):
                continue
            inherited = visible[:visible.find(piece)]
            for match in _MARGIN.finditer(piece):
                prefix = inherited + piece[:match.start()]
                if re.search(r"(?:表格|表题|表注|图题|图注|图片|插图)\s*$", prefix):
                    continue
                if not match["edge"] and not re.search(r"(?:页|页面|纸张)?边距", prefix):
                    continue
                # A table or figure margin does not authorize a later bare side as a page margin.
                if (not match["edge"]
                        and re.search(r"表格|表题|表注|图题|图注|图片|插图", inherited)
                        and not re.search(r"(?:页|页面|纸张)?边距", piece[:match.start()])):
                    continue
                value = float(match["value"]) * (10 if match["unit"].lower() in {"厘米", "cm"} else 1)
                for chinese, side in (("上", "top"), ("下", "bottom"), ("左", "left"), ("右", "right")):
                    if chinese in match["sides"]:
                        item = ("page.margins_mm." + side, value, chinese + "页边距候选")
                        if item not in values:
                            values.append(item)
    return values


def paper_values(line: str) -> list[RuleValue]:
    """Read an unambiguous A4 instruction without inventing local page scopes."""
    values: list[RuleValue] = []
    for clause in re.split(r"[。；;]", unicodedata.normalize("NFKC", line)):
        if not _PAPER_CONTEXT.search(clause) or _PAPER_UNCERTAIN.search(clause):
            continue
        sizes = {re.sub(r"\s", "", match[0]).upper() for match in re.finditer(
            r"(?<![A-Za-z0-9])[A-C]\s*[0-9](?![A-Za-z0-9])", clause, re.I)}
        landscape = bool(re.search(r"横向|横版|横式|landscape", clause, re.I))
        portrait = bool(re.search(r"纵向|竖向|竖版|纵版|portrait", clause, re.I))
        if sizes != {"A4"} or landscape and portrait:
            continue
        width, height = (297, 210) if landscape else (210, 297)
        for target, value in (("page.width_mm", width), ("page.height_mm", height)):
            item = (target, value, "A4 纸型候选")
            if item not in values:
                values.append(item)
    return values


def _font_size_value(part: str, match: re.Match[str]) -> bool:
    """Associate a point value with typography rather than another measurement."""
    before = part[:match.start()]
    after = part[match.end():]
    subjects = list(_SIZE_SUBJECT.finditer(before))
    subject = subjects[-1] if subjects else None
    boundary = max(before.rfind(","), before.rfind("，"), before.rfind("、"))
    if subject is not None and subject.lastgroup == "other" and subject.start() > boundary:
        return False
    if subject is not None and re.fullmatch(r"字号|字体|字型|文字大小", subject[0]):
        return True
    if re.match(r"\s*的?(?:行间?距|多倍行距|固定值|固定行距|段前|段后|段间距|字间距|字距|行高|缩进|边距|装订线)", after):
        return False
    following = re.match(r"\s*的?(?:字号|字体|字型|" + _CHINESE_FONT + "|" + _LATIN_FONT + ")", after, re.I)
    if following and not _SIZE.match(after[following.end():].lstrip(" 为是:：")):
        return True
    if subject is not None and subject.lastgroup == "font":
        return True
    # Named Chinese sizes already identify a font size; bare points need a
    # font/size subject. Other measurements remain in the source review item.
    return match["points"] is None


def body_values(parts: list[str]) -> list[RuleValue]:
    """Read values only from clauses already assigned to body text."""
    result: list[RuleValue] = []
    for raw in parts:
        part = unicodedata.normalize("NFKC", raw)
        # A comparison stays inside its own comma group and does not erase a neighboring value.
        comparable = re.sub(
            r"(?:行间?距|多倍行距|字号|字体|字型)[^，,。；;]{0,16}(?:不小于|不大于|不超过|不少于|至少|至多|不得|不能|不应)[^，,。；;]*",
            "", part)
        pieces = []
        for piece in re.split(r"[，,]", comparable):
            prohibited = re.search(r"不得|不能|不应|禁止|不使用|不采用|不小于|不大于|不超过|不少于|至少|至多", piece)
            if prohibited:
                continue
            pieces.append(piece)
        comparable = "，".join(pieces)
        if not comparable.strip():
            continue
        for font in re.finditer(_CHINESE_FONT, comparable):
            result.append(("body.fonts.eastAsia", font[0], "正文中文字体候选"))
        for font in re.finditer(_LATIN_FONT, comparable, re.I):
            compact = re.sub(r"\s+", "", font[0]).lower()
            name = {"timesnewroman": "Times New Roman", "新罗马": "Times New Roman", "新罗马体": "Times New Roman",
                    "arial": "Arial", "calibri": "Calibri"}[compact]
            result.append(("body.fonts.ascii", name, "正文西文字体候选"))
        for size in _SIZE.finditer(comparable):
            if not _font_size_value(comparable, size):
                continue
            value = float(size["points"]) if size["points"] else _SIZE_POINTS[size[0]]
            result.append(("body.size_pt", value, "正文磅数字号候选"))
        spacing_pieces = [piece for piece in re.split(r"[，,]", comparable)
                          if not re.search(r"可以|允许|如有|若有|必要时|视情况|特殊情况", piece)]
        spacing_source = "，".join(spacing_pieces)
        spacing = re.finditer(r"行间?距[^\d。；;]{0,20}(\d+(?:\.\d+)?)\s*倍"
                              r"|(\d+(?:\.\d+)?)\s*倍\s*行间?距"
                              r"|多倍行距\s*(\d+(?:\.\d+)?)", spacing_source)
        for match in spacing:
            result.append(("body.line_spacing", float(next(value for value in match.groups() if value)), "自动倍数行距候选"))
    return list(dict.fromkeys(result))


def _heading(line: str) -> tuple[tuple[int, ...] | None, str] | None:
    text = re.sub(r"^\s*#{1,6}\s+", "", line).strip().rstrip("：:")
    if len(text) > 60:
        return None
    numbered = re.match(r"^(\d+(?:\.\d+)*)(?:[、.．]|\s)*(\D.*)$", text)
    chinese = re.match(r"^(?:[（(]?[一二三四五六七八九十]+[)）、.．]|第[一二三四五六七八九十\d]+[章节])\s*(.+)$", text)
    if numbered:
        name = numbered[2]
        if re.match(r"倍|cm|mm|磅|pt", name, re.I):
            return None
        prefix = tuple(int(value) for value in numbered[1].split("."))
    elif chinese:
        prefix, name = None, chinese[1]
    elif (re.fullmatch(r"正文(?:格式|排版|内容|要求|文字规范)?|" + _NON_BODY_CHOICE + r"(?:格式|设置|要求)?", text)
          or _GENERAL_HEADING.fullmatch(text)):
        prefix, name = None, text
    else:
        return None
    if re.search(r"[，,。；;：:]", name):
        return None
    return prefix, name


def _body_mention(fragment: str, position: int) -> bool:
    before = fragment[:position]
    after = fragment[position + 2:]
    if re.search(r'[“「『\"][^”」』\"]{0,40}$', before):
        return False  # A quoted Word style name does not change the clause subject.
    if re.search(r"(?:样式|模板)(?:名称|名)?(?:[为是叫]|称为|定义为)?\s*$", before):
        return False
    if re.search(r"不(?:要|得|能|应|使用|采用)?\s*[与比同](?:论文)?$", before):
        return False
    if re.search(r"(?:均|都|一并|同时)(?:使用|采用|用)", after):
        return True
    if re.search(_NON_BODY_CHOICE + r"\s*的?$|[与比同](?:论文)?$", before, re.I):
        return False
    return not re.match(r"所在|以后|之后|开始|之前|页码", after)


class BodyTextContext:
    """Carry numbered subsection context; explicit subjects end inherited scope."""

    def __init__(self) -> None:
        self.sections: dict[tuple[int, ...], tuple[bool, str]] = {}
        self.section_body = False
        self.heading = ""
        self.carry_body = False
        self.carry_age = 0
        self.body_hint_age = 5
        self.furniture = False
        self.general_heading = ""
        self.general_prefix: tuple[int, ...] | None = None
        self.general_restriction: tuple[str, tuple[int, ...] | None] | None = None

    def _general_scope(self, line: str, prefix: tuple[int, ...] | None, name: str) -> None:
        chapter = bool(re.match(r"^(?:#{1,6}\s+)?(?:[（(]?[一二三四五六七八九十]+[)）、.．]|第[一二三四五六七八九十\d]+[章节])", line))
        if self.general_restriction is not None:
            kind, restricted_prefix = self.general_restriction
            numbered_peer = (kind == "numbered" and prefix is not None and restricted_prefix is not None
                             and not (len(prefix) > len(restricted_prefix)
                                      and prefix[:len(restricted_prefix)] == restricted_prefix))
            if chapter or numbered_peer:
                self.general_restriction = None
        if re.search(_NON_BODY, name, re.I):
            self.general_restriction = ("numbered" if prefix is not None else "chapter" if chapter else "bare", prefix)
        if _GENERAL_HEADING.fullmatch(name) and self.general_restriction is None:
            self.general_heading, self.general_prefix = line, prefix
        elif self.general_heading:
            descendant = prefix is not None and (
                self.general_prefix is None
                or (len(prefix) > len(self.general_prefix) and prefix[:len(self.general_prefix)] == self.general_prefix))
            if not descendant or self.general_restriction is not None:
                self.general_heading, self.general_prefix = "", None

    def _general_parts(self, line: str) -> list[str]:
        """A universal instruction under a document scope also covers its body.

        A subsection about an abstract, title, cover or other named part never
        supplies this scope. Merely listing a font under editing settings is
        insufficient: the clause must explicitly say that it applies uniformly.
        """
        if not self.general_heading:
            return []
        parts = []
        for fragment in re.split(r"[。；;]", line):
            if (re.search(_NON_BODY, fragment, re.I) or _EXAMPLE.search(fragment)
                    or re.search(r"建议|推荐|可以|允许|无需|不必|不要求|可不", fragment)
                    or not re.search(r"一律", fragment)
                    or not re.search(r"字体|行间?距", fragment)):
                continue
            parts.append(fragment)
        return parts

    def parts(self, line: str) -> tuple[list[str], str]:
        heading = _heading(line)
        if heading is not None:
            prefix, name = heading
            self._general_scope(line, prefix, name)
            # Only the active ancestor path can supply scope. A repeated
            # chapter number must not revive an earlier, unrelated subsection.
            self.sections = {key: value for key, value in self.sections.items()
                             if prefix is not None and len(key) < len(prefix) and prefix[:len(key)] == key}
            parents = [key for key in self.sections if prefix is not None and len(key) < len(prefix) and prefix[:len(key)] == key]
            inherited, inherited_heading = self.sections[max(parents, key=len)] if parents else (False, "")
            non_body = bool(re.search(_NON_BODY, name, re.I))
            self.section_body = not non_body and ("正文" in name or inherited)
            self.heading = "\n".join(item for item in (inherited_heading if self.section_body else "", line) if item)
            if prefix is not None:
                self.sections[prefix] = (self.section_body, self.heading)
            else:
                self.sections.clear()
            self.carry_body, self.carry_age, self.body_hint_age = False, 0, 0 if self.section_body else 5
            self.furniture = bool(re.search(r"页眉|页脚", name))
        elif re.match(r"^(?:页眉|页脚)(?:设置|格式)?[。:：]?", line):
            self.furniture = True
        elif re.match(r"^(?:页面设置|版面设置|页边距|正文)", line):
            self.furniture = False

        active = self.section_body or (self.carry_body and self.carry_age < 3)
        body_hint = self.body_hint_age < 4
        explicit_body = False
        result: list[str] = []
        for fragment in re.split(r"[。；;]", line):
            cursor = 0
            for match in _SUBJECT.finditer(fragment):
                if match[0] == "正文" and not _body_mention(fragment, match.start()):
                    # Mentioning the selected style must neither turn an
                    # abstract into body text nor end an explicit body clause.
                    if not explicit_body:
                        active = False
                    continue
                if active and fragment[cursor:match.start()].strip():
                    result.append(fragment[cursor:match.start()])
                subject = match[0]
                if subject == "正文" and _body_mention(fragment, match.start()):
                    active, explicit_body, body_hint = True, True, True
                elif subject in {"其余文字", "其余正文", "其他正文"}:
                    active = self.section_body or body_hint or active
                else:
                    active = False
                cursor = match.start()
            if active and fragment[cursor:].strip():
                result.append(fragment[cursor:])
        self.carry_body = active
        self.carry_age = 0 if explicit_body else self.carry_age + 1
        self.body_hint_age = 0 if explicit_body else self.body_hint_age + 1
        general = self._general_parts(line)
        result.extend(part for part in general if part not in result)
        evidence = self.heading if self.section_body else self.general_heading if general else ""
        return result, evidence
