"""Editable rule fields and expected capabilities, before reading a document."""
from __future__ import annotations

from copy import deepcopy
from typing import NotRequired, TypedDict
from ..documents.fonts import font_comparison_rules, is_font_target
from ..plugins.academic_rules import academic_fields, academic_value_schema, configured_academic_values, TARGET_LABELS
from ..plugins.structure_rules import (STRUCTURE_LABELS, STRUCTURE_PARAMETERS, configured_structure_values,
                                     structure_fields, structure_schema)
from ..persistence.school_compiler import pdf_region_compatible, requirement_scope, scope_kind, scope_unresolved, target_plugin


class RuleField(TypedDict):
    path: str
    label: str
    group: str
    type: str
    unit: NotRequired[str]
    minimum: NotRequired[int]
    exclusiveMinimum: NotRequired[int]
    maximum: NotRequired[int]
    placeholder: NotRequired[str]
    help: NotRequired[str]
    integer: NotRequired[bool]
    options: NotRequired[list[dict[str, str]]]


_FIELDS: list[RuleField] = [
    {"path": "page.width_mm", "label": "纸张宽度", "group": "页面", "type": "number", "unit": "毫米", "exclusiveMinimum": 0, "maximum": 2000},
    {"path": "page.height_mm", "label": "纸张高度", "group": "页面", "type": "number", "unit": "毫米", "exclusiveMinimum": 0, "maximum": 2000},
    *({"path": "page.margins_mm." + side, "label": label + "页边距", "group": "页面", "type": "number", "unit": "毫米", "minimum": 0, "maximum": 200}
      for side, label in (("top", "上"), ("bottom", "下"), ("left", "左"), ("right", "右"))),
    {"path": "body.font", "label": "默认正文字体", "group": "正文", "type": "text", "placeholder": "例如：宋体", "help": "单独设置的中文、西文字体优先于默认字体。"},
    {"path": "body.fonts.eastAsia", "label": "中文字体", "group": "正文", "type": "text", "placeholder": "例如：宋体"},
    {"path": "body.fonts.ascii", "label": "西文字体", "group": "正文", "type": "text", "placeholder": "例如：Times New Roman"},
    {"path": "body.size_pt", "label": "正文字号", "group": "正文", "type": "number", "unit": "磅", "exclusiveMinimum": 0, "maximum": 200, "help": "例如：小四为 12 磅。"},
    {"path": "body.line_spacing", "label": "正文行距", "group": "正文", "type": "number", "unit": "倍", "exclusiveMinimum": 0, "maximum": 200},
    {"path": "body.style_ids", "label": "正文样式范围", "group": "正文", "type": "lines", "placeholder": "每行一个样式 ID", "help": "留空使用文档的默认段落样式；指定时应填写文档中的样式 ID。"},
    {"path": "required_headings", "label": "必需章节", "group": "章节", "type": "lines", "placeholder": "每行一个标题，例如：摘要", "help": "按独立标题匹配，不按正文中提到该词判定。"},
]


def profile_fields() -> dict:
    from ..plugins.fields import FIELD_LABELS
    return {"schema_version": 1, "plugin_id": "generic-format", "fields": deepcopy(_FIELDS),
            "school_targets": school_target_fields(),
            "academic_fields": {"plugin_id": "academic-format", "fields": academic_fields()},
            "structure_fields": {"plugin_id": "academic-structure", "fields": structure_fields()},
            "document_fields": {"plugin_id": "document-fields",
                "field_options": [{"value": name, "label": labels[0]} for name, labels in FIELD_LABELS.items()],
                "missing_policies": [
                    {"value": "review", "label": "未找到时人工核对"},
                    {"value": "fail_when_complete", "label": "完整标签表单缺项时报告错误"}],
                "missing_policy_help": "仅当学校要求原稿使用字段标签填写时选择标签表单；OCR或文字覆盖不完整时仍需人工核对。"}}


def school_target_fields() -> list[dict]:
    fields: list[dict] = []
    for item in _FIELDS:
        target = "required_heading" if item["path"] == "required_headings" else item["path"]
        value_schema: dict = {"type": "string", "minLength": 1}
        if item["type"] == "number":
            value_schema = {"type": "number", **{key: value for key, value in item.items() if key in {"minimum", "maximum", "exclusiveMinimum"}}}
        elif item["type"] == "lines" and target != "required_heading":
            value_schema = {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 100}
        fields.append({"target": target, "label": item["label"], "type": "text" if target == "required_heading" else item["type"],
                       "plugin_id": "generic-format", "value_schema": value_schema})
    for target, label in TARGET_LABELS.items():
        schema = academic_value_schema(target)
        fields.append({"target": target, "label": label, "plugin_id": "academic-format", "value_schema": schema,
                       "type": "number" if schema.get("type") in {"number", "integer"} else "select" if "enum" in schema else "text"})
    for target, label, schema in (
        ("references.heading_after_lines", "参考文献标题段后距", {"type": "number", "minimum": 0, "maximum": 200}),
        ("references.entry_hanging_chars", "参考文献悬挂缩进", {"type": "number", "minimum": 0, "maximum": 200}),
        ("references.citation_order", "引用首次顺序", {"enum": ["ascending"]}),
        ("references.citation_unique", "不得重复引用", {"type": "boolean"}),
    ):
        fields.append({"target": target, "label": label, "plugin_id": "generic-format", "value_schema": schema,
                       "type": "boolean" if schema.get("type") == "boolean" else "select" if "enum" in schema else "number"})
    from ..plugins.fields import FIELD_LABELS
    fields.extend({"target": "field." + key, "label": labels[0], "plugin_id": "document-fields", "type": "text",
                   "value_schema": {"type": ["string", "null"], "maxLength": 120}} for key, labels in FIELD_LABELS.items())
    structure = structure_schema()["properties"]
    controls = {item["path"]: item for item in structure_fields()}
    for target, label in STRUCTURE_LABELS.items():
        group, key = target.split(".")[1:]
        schema = structure[group]["properties"][key]
        parameters = {name: structure[group]["properties"][name] for name in STRUCTURE_PARAMETERS[group]}
        fields.append({"target": target, "label": label, "plugin_id": "academic-structure", "value_schema": schema,
                       "type": controls[target]["type"],
                       "options": controls[target].get("options", []),
                       "const_options": [{"value": "continue", "label": "接续前节"}] if target == "structure.page_numbers.start" else [],
                       "parameter_fields": [{**controls["structure." + group + "." + name], "path": name,
                                             "value_schema": value} for name, value in parameters.items()],
                       "parameters_schema": {"type": "object", "properties": parameters, "additionalProperties": False}})
    for item in fields:
        item.update(scope=scope_kind(item["target"]), allow_global_scope=item["target"].startswith(("page.", "section.")))
        if is_font_target(item["target"]):
            item["comparison"] = font_comparison_rules()
        item.setdefault("parameter_fields", [])
        item.setdefault("parameters_schema", {"type": "object", "properties": {}, "additionalProperties": False})
        schema = item["value_schema"]
        if "enum" in schema and not item.get("options"):
            item["options"] = [{"value": value, "label": str(value)} for value in schema["enum"]]
    return fields


def _get(settings: dict, path: str):
    value = settings
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def effective_summary(profile: dict, kind: str | None, input_format: str, plugins: list[dict]) -> dict:
    """Describe configured groups, never pretend that document checks have run."""
    settings = profile.get("settings", {})
    available = {plugin["id"]: plugin.get("available", False) for plugin in plugins}
    items: list[dict] = []
    labels = {**{field["path"]: field["label"] for field in _FIELDS}, **TARGET_LABELS, **STRUCTURE_LABELS}
    paths = [field["path"] for field in _FIELDS]
    paths += ["body.fonts." + slot for slot in settings.get("body", {}).get("fonts", {}) if "body.fonts." + slot not in paths]
    paths += ["references." + key for key in ("heading_after_lines", "entry_hanging_chars", "citation_order", "citation_unique")]
    paths += ["fields.required"]
    paths += [target for target, _ in configured_academic_values(settings)]
    paths += [target for target, _ in configured_structure_values(settings)]
    declared_targets = set()
    scoped_targets = {item["target"] for item in profile.get("scoped_rules", [])}
    for path in paths:
        if path in scoped_targets:
            continue
        value = _get(settings, path)
        if path == "fields.required" and settings.get("fields", {}).get("expected"):
            value = list(dict.fromkeys([*(value or []), *settings["fields"]["expected"]]))
        if value is None or value == [] or value is False or (path == "references.citation_order" and value == "none"):
            continue
        owner = ("academic-structure" if path in STRUCTURE_LABELS else "academic-format" if path in TARGET_LABELS
                 else "document-fields" if path.startswith("fields.") else "generic-format")
        state, reason = "conditional", "读取原稿后按实际证据判断"
        if owner not in profile.get("plugins", []) or not available.get(owner):
            state, reason = "unavailable", "所需插件当前不可用"
        elif owner in {"academic-format", "academic-structure"} and input_format != "docx":
            state, reason = "unsupported", "该格式不保存 Word 段落、大纲级别或分节设置"
        elif input_format in {"txt", "md", "json"} and (path.startswith(("page.", "body.")) or path in {"references.heading_after_lines", "references.entry_hanging_chars"}):
            state, reason = "unsupported", "该格式不保存实际排版属性"
        elif input_format == "pdf":
            if path.startswith("page.margins_mm.") or path in {"body.style_ids", "body.line_spacing", "references.heading_after_lines", "references.entry_hanging_chars"}:
                state, reason = "unsupported", "PDF 不保存 Word 段落或页边距设置"
            elif path.startswith("body."):
                state, reason = ("conditional", "仅比较明确正文区域内可核对的原生文字") if settings.get("body", {}).get("pdf_region_mm") else ("manual", "需先明确 PDF 正文检查范围")
            else:
                reason = "按实际 PDF 证据检查；OCR 和提取不完整部分仍需复核"
        if kind and kind not in profile.get("kinds", ("thesis", "intern", "certificate")):
            state, reason = "unavailable", "方案不适用于所选材料类型"
        item: dict = {"target": path, "label": labels.get(path, {
            "references.heading_after_lines": "参考文献标题段后距", "references.entry_hanging_chars": "参考文献悬挂缩进",
            "references.citation_order": "引用顺序", "references.citation_unique": "重复引用", "fields.required": "必需字段",
        }.get(path, path)), "expected": value, "state": state, "reason": reason}
        if path == "fields.required" and state != "unavailable":
            item["reason"] = ("按必填标签表单检查；只有正文文字覆盖充分时才判缺项，OCR和未知内容保留复核"
                              if settings.get("fields", {}).get("missing_policy") == "fail_when_complete"
                              else "明确空值可报告错误；普通正文未匹配时人工核对")
        if path.startswith(("body.", "paragraph.")):
            group, prop = path.split(".", 1)
            scope_settings = settings.get(group, {})
            default_scope = ["文档默认段落样式"] if group == "body" and profile.get("school") is None else []
            item["scope"] = scope_settings.get("property_style_ids", {}).get(prop, scope_settings.get("style_ids", default_scope))
            if (input_format == "docx" and not item["scope"] and state == "conditional"
                    and (group == "paragraph" or profile.get("school") is not None)):
                item.update(state="manual", reason="须先确认正文段落样式范围")
        items.append(item)
        declared_targets.add("required_heading" if path == "required_headings" else path)
        if path == "fields.required":
            declared_targets.update("field." + key for key in value if isinstance(key, str))
    for requirement in profile.get("requirements", []):
        if kind and requirement.get("kind") != kind:
            continue
        target = requirement.get("target")
        if requirement.get("excluded"):
            state, reason = "excluded", requirement.get("exclusion_reason", "已排除")
        elif not requirement.get("confirmed"):
            state, reason = "manual", "要求尚未确认"
        elif requirement.get("expected") is False and str(target).startswith("structure."):
            state, reason = "manual", "该检查已关闭，不计为自动通过"
        elif scope_unresolved(requirement) and input_format == "docx":
            state, reason = "manual", "须先确认实际原稿的检查范围"
        elif any(item.get("id") == requirement.get("id") for item in profile.get("scoped_rules", [])):
            owner = target_plugin(str(target))
            if input_format == "pdf" and (target in {"body.font", "body.size_pt"} or str(target).startswith("body.fonts.")):
                state, reason = (("conditional", "仅比较明确正文区域内可核对的原生文字")
                                 if pdf_region_compatible(requirement, profile) and settings.get("body", {}).get("pdf_region_mm") else
                                 ("manual", "须确认PDF正文区域；一个区域不能替代不同DOCX样式范围"))
            else:
                state, reason = ("unsupported", "该属性需要DOCX结构证据") if input_format != "docx" else ("conditional", "按已确认原稿范围逐条执行")
            if owner not in profile.get("plugins", []) or not available.get(owner):
                state, reason = "unavailable", "所需插件不可用"
        elif requirement.get("mode") != "automatic" or target not in declared_targets:
            state, reason = "manual", "人工条款或未声明自动检查能力"
        else:
            continue
        scope_type, scope = requirement_scope(requirement)
        items.append({"target": target, "requirement_id": requirement.get("id"), "label": requirement.get("label") or target,
                      "expected": requirement.get("expected"), "state": state, "reason": reason, "scope": scope,
                      "scope_type": scope_type, "parameters": requirement.get("parameters", {})})
    if "legacy-school" in profile.get("plugins", []):
        items.append({
            "target": "legacy.rules", "label": "学校专项规则",
            "state": "manual" if available.get("legacy-school") else "unavailable",
            "reason": (
                "依赖可选外部专项引擎；不可用时不等于学校要求未配置，"
                "可改用「学校要求」生成方案或预置方案"
            ),
        })
    for plugin_id in profile.get("plugins", []):
        if plugin_id not in {"docx-package", "generic-format", "document-fields", "legacy-school", "academic-format", "academic-structure"}:
            items.append({"target": plugin_id + ".rules", "label": plugin_id + " 插件规则", "state": "manual" if available.get(plugin_id) else "unavailable", "reason": "插件独立规则范围以实际执行证据为准"})
    if "generic-format" in profile.get("plugins", []):
        items.append({"target": "layout.visual", "label": "最终版式", "state": "manual", "reason": "分页、图表和打印效果需结合实际页面核对"})
    if settings.get("fields", {}).get("review_signatures"):
        items.append({"target": "fields.signatures", "label": "签字与盖章", "state": "manual", "reason": "需要人工核对，不认定材料真实性"})
    counts = {state: sum(item["state"] == state for item in items) for state in ("conditional", "manual", "unsupported", "excluded", "unavailable")}
    school = profile.get("school", {})
    return {"profile_id": profile["id"], "profile_name": profile["name"], "version": profile.get("version", 1),
            "kind": kind, "input_format": input_format, "source": {"name": school.get("name", "自定义/内置规则方案"), "version": school.get("version")},
            "items": items, "counts": counts, "disclaimer": "以上按配置项预计能力；实际执行次数、属性是否可读和符合情况以检测报告为准。"}
