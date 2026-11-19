"""Compile confirmed requirements without collapsing distinct execution scopes."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from ..documents.fonts import is_font_target, normalize_font_name
from ..plugins.academic_rules import ACADEMIC_TARGETS, normalize_style_ids
from ..plugins.structure_rules import STRUCTURE_LABELS, validate_structure_parameters, validate_structure_requirement

SCOPE_FIELDS = ("scope_style_ids", "scope_section_indices", "scope_binding_status", "parameters",
                "source_scope_style_ids", "source_scope_section_indices", "source_parameters")


def value_key(value: Any) -> str:
    """Canonical JSON identity keeps equivalent numeric measurements together."""
    def normalized(item: Any) -> Any:
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalized(part) for part in item]
        if isinstance(item, dict):
            return {key: normalized(part) for key, part in item.items()}
        return item
    return json.dumps(normalized(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def expected_key(target: str, value: Any) -> str:
    """Compare font families without rewriting a requirement's source evidence."""
    normalized = normalize_font_name(value) if is_font_target(target) else None
    return value_key(normalized if normalized is not None else value)


def section_indices(value: object, name: str = "分节范围") -> list[int]:
    if (not isinstance(value, list) or len(value) > 100
            or any(type(index) is not int or not 1 <= index <= 1000 for index in value)
            or len(set(value)) != len(value)):
        raise ValueError(name + "须为最多100个不重复的正整数分节序号")
    return sorted(value)


def scope_kind(target: str) -> str:
    if target.startswith(("body.", "paragraph.", "headings.")) and target != "body.style_ids":
        return "styles"
    if target.startswith("structure.captions."):
        return "styles"
    if target.startswith(("page.", "section.", "structure.page_numbers.")):
        return "sections"
    return "global"


def requirement_scope(item: dict) -> tuple[str, list]:
    target = item["target"]
    kind = scope_kind(target)
    parameters = item.get("parameters", {})
    if kind == "styles":
        return kind, item.get("scope_style_ids") or parameters.get("style_ids", [])
    if kind == "sections":
        return kind, item.get("scope_section_indices") or parameters.get("section_indices", [])
    return kind, []


def validate_requirement_scope(item: dict, *, draft: bool = False) -> None:
    for field in ("scope_style_ids", "source_scope_style_ids"):
        if field in item:
            normalize_style_ids(item[field], field)
    for field in ("scope_section_indices", "source_scope_section_indices"):
        if field in item:
            section_indices(item[field], field)
    if "scope_binding_status" in item and item["scope_binding_status"] not in {"bound", "unbound"}:
        raise ValueError("范围绑定状态须为bound/unbound")
    kind = scope_kind(item["target"])
    for field, compatible in (("scope_style_ids", "styles"), ("source_scope_style_ids", "styles"),
                              ("scope_section_indices", "sections"), ("source_scope_section_indices", "sections")):
        if item.get(field) and kind != compatible:
            raise ValueError("该规则不支持所填作用范围类型：" + field)
    for field in ("parameters", "source_parameters"):
        if field in item:
            if item["target"] not in STRUCTURE_LABELS:
                if item[field] != {}:
                    raise ValueError("该目标不接受结构配套参数")
            else:
                validate_structure_parameters(item["target"], item[field])
                prefix = "source_scope_" if field == "source_parameters" else "scope_"
                for key in ("style_ids", "section_indices"):
                    if item.get(prefix + key) and item[field].get(key) and set(item[prefix + key]) != set(item[field][key]):
                        raise ValueError("作用范围与结构配套范围参数不一致")
    if not draft and item["target"] in STRUCTURE_LABELS and item.get("mode") == "automatic" and item.get("confirmed") and not item.get("excluded"):
        validate_structure_requirement(item["target"], item.get("expected"), item.get("parameters"))


def needs_binding(item: dict) -> bool:
    kind, values = requirement_scope(item)
    return kind == "styles" or kind == "sections" and (bool(values) or item["target"].startswith("structure.page_numbers."))


def scope_unresolved(item: dict) -> bool:
    _, values = requirement_scope(item)
    return item.get("scope_binding_status") == "unbound" or needs_binding(item) and not values


def pdf_region_compatible(item: dict, profile: dict) -> bool:
    """A shared PDF region cannot replace distinct DOCX role selectors."""
    if item.get("scope_style_ids") or item.get("source_scope_style_ids"):
        return False
    return all(expected_key(item["target"], other.get("expected")) == expected_key(item["target"], item.get("expected"))
               for other in profile.get("requirements", [])
               if other.get("target") == item["target"] and other.get("kind") == item["kind"]
               and other.get("confirmed") and other.get("mode") == "automatic" and not other.get("excluded"))


def requirement_conflicts(requirements: list[dict], confirmed_only: bool = False) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in requirements:
        if (item.get("excluded") or item.get("mode") != "automatic"
                or confirmed_only and item.get("confirmed") is not True or item.get("target") == "required_heading"):
            continue
        if item.get("expected") is False and item.get("target") in STRUCTURE_LABELS:
            continue
        groups.setdefault((item["kind"], item["target"]), []).append(item)
        if item["target"] in {"body.line_spacing", "paragraph.line_spacing_pt"}:
            groups.setdefault((item["kind"], "body.line_spacing / paragraph.line_spacing_pt"), []).append(item)
    conflicts = []
    for (kind, target), items in groups.items():
        prepared = []
        for item in items:
            parameters = {key: value for key, value in item.get("parameters", {}).items() if key not in {"style_ids", "section_indices"}}
            scope_type, scope = requirement_scope(item)
            if item.get("scope_binding_status") == "unbound":
                scope = item.get("source_scope_style_ids" if scope_type == "styles" else "source_scope_section_indices", scope)
            prepared.append((item, parameters, scope_type, set(scope)))
        conflicting: dict[str, dict] = {}
        for index, (first, first_parameters, first_kind, first_scope) in enumerate(prepared):
            for second, second_parameters, second_kind, second_scope in prepared[index + 1:]:
                cross_spacing = target == "body.line_spacing / paragraph.line_spacing_pt"
                if cross_spacing and first["target"] == second["target"]:
                    continue
                if {first.get("scope_binding_status"), second.get("scope_binding_status")} == {"bound", "unbound"}:
                    continue  # An explicitly deferred requirement will not execute.
                if not cross_spacing and expected_key(target, first.get("expected")) == expected_key(target, second.get("expected")) and first_parameters == second_parameters:
                    continue
                if first_kind == second_kind and first_scope and second_scope and first_scope.isdisjoint(second_scope):
                    continue
                conflicting[first["id"]] = first
                conflicting[second["id"]] = second
            if len(conflicting) == len(items):
                break
        if conflicting:
            conflicts.append({"kind": kind, "target": target, "requirements": list(conflicting),
                              "values": [item.get("expected") for item in conflicting.values()]})
    return conflicts


def target_plugin(target: str) -> str:
    return ("academic-structure" if target in STRUCTURE_LABELS else "academic-format" if target in ACADEMIC_TARGETS
            else "document-fields" if target.startswith("field.") else "generic-format")


def _write(settings: dict, path: str, value: object) -> None:
    current = settings
    parts = path.split(".")
    for key in parts[:-1]:
        current = current.setdefault(key, {})
    current[parts[-1]] = deepcopy(value)


def remove_target(settings: dict, target: str) -> None:
    if target == "required_heading":
        settings.pop("required_headings", None)
        return
    if target.startswith("field."):
        fields = settings.get("fields", {})
        name = target.removeprefix("field.")
        fields["required"] = [key for key in fields.get("required", []) if key != name]
        fields.get("expected", {}).pop(name, None)
        return
    current = settings
    parts = target.split(".")
    for key in parts[:-1]:
        if not isinstance(current.get(key), dict):
            return
        current = current[key]
    current.pop(parts[-1], None)


def rule_settings(item: dict) -> dict:
    target, expected = item["target"], item.get("expected")
    result: dict[str, Any] = {}
    if target in STRUCTURE_LABELS:
        group, key = target.split(".")[1:]
        parameters = validate_structure_requirement(target, expected, item.get("parameters"))
        scope_type, scope = requirement_scope(item)
        if scope_type == "styles" and scope:
            parameters["style_ids"] = list(scope)
        if scope_type == "sections" and scope:
            parameters["section_indices"] = list(scope)
        result["structure"] = {group: {**parameters, key: expected}}
    elif target == "required_heading":
        result["required_headings"] = [expected]
    elif target.startswith("field."):
        name = target.removeprefix("field.")
        result["fields"] = {"required": [name], "expected": {name: expected} if expected is not None else {}}
    else:
        _write(result, target, expected)
        if target.startswith(("body.", "paragraph.")) and target != "body.style_ids":
            group, prop = target.split(".", 1)
            scope = list(requirement_scope(item)[1])
            result[group].update(style_ids=scope, property_style_ids={prop: scope})
    return result


def compile_requirement_profile(profile: dict, kind: str) -> dict:
    """Return an independent execution profile; never write source records."""
    result = deepcopy(profile)
    requirements = result.get("requirements", [])
    for item in requirements:
        validate_requirement_scope(item)
    conflicts = requirement_conflicts(requirements, confirmed_only=True)
    if conflicts:
        raise ValueError("已确认要求的作用范围重叠或未知且值冲突：" + ", ".join(item["target"] for item in conflicts))
    active = [item for item in requirements if item.get("kind") == kind and item.get("confirmed")
              and item.get("mode") == "automatic" and not item.get("excluded")]
    settings = deepcopy(result.get("settings", {}))
    # Remove only values controlled by these requirements. Other profile options
    # (tolerances and reading policies) remain independent and immutable.
    for item in requirements:
        if item.get("kind") == kind and item.get("mode") == "automatic":
            remove_target(settings, item["target"])
    explicit = sorted({style for item in active if item["target"] == "body.style_ids" for style in item.get("expected", [])})
    grouped: dict[str, list[dict]] = {}
    for item in active:
        if item["target"].startswith(("body.", "paragraph.")) and item["target"] != "body.style_ids" and not item.get("scope_style_ids") and explicit:
            item["scope_style_ids"] = list(explicit)
        grouped.setdefault(item["target"], []).append(item)
    scoped = []
    property_scopes: dict[str, dict[str, list[str]]] = {}
    for target, items in grouped.items():
        distinct = {expected_key(target, item.get("expected")) for item in items}
        use_scoped = (target != "required_heading" and (len(distinct) > 1 or target in STRUCTURE_LABELS or any(needs_binding(item) for item in items)
                      or any(item.get("scope_binding_status") == "unbound" for item in items)))
        if use_scoped:
            scoped.extend({**deepcopy(item), "plugin_id": target_plugin(target)} for item in items)
        if len(distinct) != 1 and target != "required_heading":
            continue
        # Keep the ordinary single-value projection for existing profile editors.
        # The runner removes managed targets before executing scoped instances.
        item = items[0]
        if target == "required_heading":
            settings["required_headings"] = list(dict.fromkeys(value["expected"] for value in items))
        elif target.startswith("field."):
            fields = settings.setdefault("fields", {"required": [], "expected": {}})
            name = target.removeprefix("field.")
            fields.setdefault("required", []).append(name)
            if item.get("expected") is not None:
                fields.setdefault("expected", {})[name] = item["expected"]
        elif target in STRUCTURE_LABELS:
            # Each rule owns its own auxiliary options; no shared-group overwrite.
            continue
        else:
            _write(settings, target, item.get("expected"))
            if target.startswith(("body.", "paragraph.")) and target != "body.style_ids":
                group, prop = target.split(".", 1)
                property_scopes.setdefault(group, {})[prop] = sorted({style for value in items for style in value.get("scope_style_ids", [])})
    for group, scopes in property_scopes.items():
        settings.setdefault(group, {}).update(property_style_ids=scopes, style_ids=sorted({*explicit, *(style for values in scopes.values() for style in values)}))
    result["settings"] = settings
    if scoped:
        result["scoped_rules"] = scoped
    else:
        result.pop("scoped_rules", None)
    plugins = list(result.get("plugins", ["docx-package", "generic-format", "document-fields"]))
    for item in active:
        owner = target_plugin(item["target"])
        if owner not in plugins:
            plugins.append(owner)
    result["plugins"] = plugins
    return result
