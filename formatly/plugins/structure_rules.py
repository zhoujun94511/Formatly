"""Explicit options and portable schemas for document structure checks."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .academic_rules import normalize_style_ids

STRUCTURE_LABELS = {
    "structure.headings.hierarchy": "标题层级连续性",
    "structure.headings.chapter_page_break": "章前分页设置",
    "structure.captions.numbering": "图表题编号",
    "structure.captions.require_reference": "图表正文引用",
    "structure.references.correspondence": "引用与参考文献对应",
    "structure.references.require_all_cited": "参考文献被引情况",
    "structure.page_numbers.require_field": "分节页码域",
    "structure.page_numbers.format": "分节页码格式",
    "structure.page_numbers.start": "分节页码起始值",
}
PAGE_FORMATS = ("decimal", "lowerRoman", "upperRoman", "lowerLetter", "upperLetter")
_BOOLS = {"headings": ("hierarchy", "chapter_page_break"), "captions": ("require_reference",),
          "references": ("correspondence", "require_all_cited"), "page_numbers": ("require_field",)}
STRUCTURE_PARAMETERS = {
    "headings": ("chapter_level",),
    "captions": ("style_ids", "figure_label", "table_label", "start"),
    "references": ("heading",),
    "page_numbers": ("section_indices",),
}


def validate_structure_parameters(target: str, parameters: object = None) -> dict:
    """Validate auxiliary controls independently of an unfinished value editor."""
    if target not in STRUCTURE_LABELS:
        raise ValueError("不支持的结构检查目标")
    group = target.split(".")[1]
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict) or set(parameters) - set(STRUCTURE_PARAMETERS[group]):
        raise ValueError(target + "包含不支持的配套参数")
    validate_structure_settings({"structure": {group: parameters}})
    return deepcopy(parameters)


def validate_structure_requirement(target: str, expected: object, parameters: object = None) -> dict:
    parameters = validate_structure_parameters(target, parameters)
    group, key = target.split(".")[1:]
    validate_structure_settings({"structure": {group: {**parameters, key: expected}}})
    return parameters


def structure_schema() -> dict:
    def group(properties: dict) -> dict:
        return {"type": "object", "properties": properties, "additionalProperties": False}
    nonblank = {"type": "string", "pattern": r"\S", "maxLength": 120}
    positive = {"type": "integer", "minimum": 1, "maximum": 100000}
    return group({
        "headings": group({"hierarchy": {"type": "boolean"}, "chapter_page_break": {"type": "boolean"},
                           "chapter_level": {"type": "integer", "minimum": 1, "maximum": 9}}),
        "captions": group({"style_ids": {"type": "array", "maxItems": 100, "items": nonblank},
                           "figure_label": nonblank, "table_label": nonblank,
                           "numbering": {"enum": ["continuous", "chapter"]}, "start": positive,
                           "require_reference": {"type": "boolean"}}),
        "references": group({"heading": nonblank, "correspondence": {"type": "boolean"},
                             "require_all_cited": {"type": "boolean"}}),
        "page_numbers": group({"require_field": {"type": "boolean"}, "format": {"enum": list(PAGE_FORMATS)},
                               "start": {"anyOf": [positive, {"const": "continue"}]},
                               "section_indices": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                                                   "items": {"type": "integer", "minimum": 1, "maximum": 1000}}}),
    })


def validate_structure_settings(settings: dict) -> None:
    structure = settings.get("structure", {})
    shape = structure_schema()["properties"]
    if not isinstance(structure, dict) or set(structure) - set(shape):
        raise ValueError("structure包含不支持的结构规则组")
    for group, rules in structure.items():
        if not isinstance(rules, dict) or set(rules) - set(shape[group]["properties"]):
            raise ValueError("structure." + group + "包含不支持的参数")
        for key, value in rules.items():
            path = "structure." + group + "." + key
            if key in _BOOLS[group]:
                if type(value) is not bool:
                    raise ValueError(path + "须为布尔值")
            elif key == "style_ids":
                normalize_style_ids(value, path)
            elif key == "section_indices":
                if (not isinstance(value, list) or not value or len(value) > 100
                        or any(type(index) is not int or not 1 <= index <= 1000 for index in value)
                        or len(set(value)) != len(value)):
                    raise ValueError(path + "须为最多100个不重复的分节序号")
            elif key in ("start", "chapter_level"):
                if key == "start" and group == "page_numbers" and value == "continue":
                    continue
                if type(value) is not int or not 1 <= value <= (9 if key == "chapter_level" else 100000):
                    raise ValueError(path + "须为有效正整数")
            elif key == "numbering":
                if not isinstance(value, str) or value not in ("continuous", "chapter"):
                    raise ValueError(path + "仅支持continuous/chapter")
            elif key == "format":
                if not isinstance(value, str) or value not in PAGE_FORMATS:
                    raise ValueError(path + "不是支持的页码格式")
            elif not isinstance(value, str) or not value.strip() or len(value) > 120:
                raise ValueError(path + "须为最多120字符的非空文本")
    labels = structure.get("captions", {})
    if labels.get("figure_label", "图").strip().casefold() == labels.get("table_label", "表").strip().casefold():
        raise ValueError("图题与表题标签不能相同")


def configured_structure_values(settings: dict):
    for group, rules in settings.get("structure", {}).items():
        for key, value in rules.items():
            target = "structure." + group + "." + key
            if target in STRUCTURE_LABELS and value is not False:
                yield target, value


def structure_fields() -> list[dict]:
    groups = {"headings": "标题结构", "captions": "图表题注", "references": "文献对应", "page_numbers": "页码设置"}
    result: list[dict] = []
    for target, label in STRUCTURE_LABELS.items():
        group, key = target.split(".")[1:]
        field: dict[str, Any] = {"path": target, "label": label, "group": groups[group], "type": "boolean"}
        if key == "numbering":
            field.update(type="select", options=[{"value": "continuous", "label": "全文连续"}, {"value": "chapter", "label": "按章编号"}])
        elif key == "format":
            field.update(type="select", options=[{"value": fmt, "label": label_text} for fmt, label_text in zip(
                PAGE_FORMATS, ("阿拉伯数字", "小写罗马数字", "大写罗马数字", "小写字母", "大写字母"))])
        elif key == "start":
            field.update(type="number", minimum=1, maximum=100000, integer=True,
                         help="指定重新编号的起始值；接续前节可在高级JSON中填写 continue。")
        result.append(field)
    result.extend([
        {"path": "structure.headings.chapter_level", "label": "章标题级别", "group": "标题结构", "type": "number", "minimum": 1, "maximum": 9, "integer": True},
        {"path": "structure.captions.style_ids", "label": "题注样式范围", "group": "图表题注", "type": "lines", "help": "填写已确认的题注样式ID；留空保留人工核对。"},
        {"path": "structure.captions.figure_label", "label": "图题标签", "group": "图表题注", "type": "text", "placeholder": "图"},
        {"path": "structure.captions.table_label", "label": "表题标签", "group": "图表题注", "type": "text", "placeholder": "表"},
        {"path": "structure.captions.start", "label": "题注起始编号", "group": "图表题注", "type": "number", "minimum": 1, "maximum": 100000, "integer": True},
        {"path": "structure.references.heading", "label": "参考文献章节标题", "group": "文献对应", "type": "text", "placeholder": "参考文献"},
        {"path": "structure.page_numbers.section_indices", "label": "目标分节序号", "group": "页码设置", "type": "lines",
         "help": "实际原稿中从1开始的分节序号，每行一个；学校局部要求须确认原稿范围。"},
    ])
    schema = structure_schema()["properties"]
    for item in result:
        group, key = item["path"].split(".")[1:]
        item["value_schema"] = schema[group]["properties"][key]
        if item["path"] == "structure.page_numbers.start":
            item["const_options"] = [{"value": "continue", "label": "接续前节"}]
    return deepcopy(result)
