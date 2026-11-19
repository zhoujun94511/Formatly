"""Portable JSON Schema documents for Formatly's public data contracts."""
from __future__ import annotations

from copy import deepcopy
from ..plugins.academic_rules import ACADEMIC_TARGETS, academic_value_schema, academic_settings_schema
from ..plugins.structure_rules import STRUCTURE_LABELS, STRUCTURE_PARAMETERS, structure_schema


DIALECT = "https://json-schema.org/draft/2020-12/schema"
KINDS = ["thesis", "intern", "certificate"]
CHECK_STATES = ["passed", "failed", "manual", "not_checked", "unsupported", "error", "not_applicable"]
_TEXT = {"type": "string"}
_NONBLANK = {"type": "string", "pattern": r"\S"}
_IDENTIFIER = {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,63}$"}
_HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
_SOURCE = {"type": ["string", "object", "array", "null"]}


def _number(maximum: int, *, positive=False) -> dict:
    return {"type": "number", "exclusiveMinimum" if positive else "minimum": 0, "maximum": maximum}


def _object(properties: dict, *, required=(), additional=True) -> dict:
    value: dict = {"type": "object", "properties": properties, "additionalProperties": additional}
    if required:
        value["required"] = list(required)
    return value


_STYLE_IDS = {"type": "array", "maxItems": 100, "items": {**_NONBLANK, "maxLength": 120}}
_SECTION_INDICES = {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"type": "integer", "minimum": 1, "maximum": 1000}}
_REQUIREMENT = _object({
    "id": {"type": "string", "minLength": 1}, "kind": {"enum": KINDS}, "target": {"type": "string", "minLength": 1},
    "mode": {"enum": ["automatic", "manual"]}, "confirmed": {"type": "boolean"}, "expected": {},
    "excluded": {"type": "boolean", "default": False}, "exclusion_reason": _TEXT,
    "label": _TEXT, "source_id": {"type": ["string", "null"]},
    "source_locator": {"type": ["string", "null"]}, "source_excerpt": {"type": ["string", "null"]},
    "scope_style_ids": {"$ref": "#/$defs/styleIds"},
    "scope_section_indices": _SECTION_INDICES,
    "scope_binding_status": {"enum": ["bound", "unbound"]},
    "source_scope_style_ids": {"$ref": "#/$defs/styleIds"}, "source_scope_section_indices": _SECTION_INDICES,
    "parameters": {"type": "object"}, "source_parameters": {"type": "object"},
}, required=("id", "kind", "target", "mode", "confirmed"))
_REQUIREMENT["allOf"] = [
    {"if": {"required": ["excluded"], "properties": {"excluded": {"const": True}}},
     "then": {"required": ["exclusion_reason"], "properties": {"confirmed": {"const": True}, "exclusion_reason": _NONBLANK}}},
    {"if": {"required": ["target", "mode", "confirmed"],
            "properties": {"target": {"const": "body.style_ids"}, "mode": {"const": "automatic"},
                           "confirmed": {"const": True}, "excluded": {"const": False}}},
     "then": {"required": ["expected"], "properties": {"expected": {"allOf": [{"$ref": "#/$defs/styleIds"}], "minItems": 1}}}},
]
_REQUIREMENT["allOf"].extend(
    {"if": {"required": ["target", "mode", "confirmed"],
            "properties": {"target": {"const": target}, "mode": {"const": "automatic"},
                           "confirmed": {"const": True}, "excluded": {"const": False}}},
     "then": {"required": ["expected"], "properties": {"expected": academic_value_schema(target)}}}
    for target in sorted(ACADEMIC_TARGETS))
_REQUIREMENT["allOf"].extend(
    {"if": {"required": ["target", "mode", "confirmed"],
            "properties": {"target": {"const": target}, "mode": {"const": "automatic"}, "confirmed": {"const": True}, "excluded": {"const": False}}},
     "then": {"required": ["expected"], "properties": {"expected": structure_schema()["properties"][target.split(".")[1]]["properties"][target.split(".")[2]]}}}
    for target in STRUCTURE_LABELS)
_REQUIREMENT["allOf"].extend(
    {"if": {"required": ["target"], "properties": {"target": {"const": target}}},
     "then": {"properties": {field: _object({key: structure_schema()["properties"][target.split(".")[1]]["properties"][key]
                                               for key in STRUCTURE_PARAMETERS[target.split(".")[1]]}, additional=False)
                              for field in ("parameters", "source_parameters")}}}
    for target in STRUCTURE_LABELS)

_SIDES = {side: _number(200) for side in ("top", "bottom", "left", "right")}
_BODY_SCOPE = ("font", "size_pt", "line_spacing", "fonts.eastAsia", "fonts.ascii", "fonts.hAnsi", "fonts.cs")
_FIELD_NAMES = ("name", "student_id", "organization", "start_date", "end_date")
_SETTINGS = _object({
    "structure": structure_schema(),
    **academic_settings_schema({"$ref": "#/$defs/styleIds"}),
    "page": _object({"width_mm": _number(2000, positive=True), "height_mm": _number(2000, positive=True), "tolerance_mm": _number(2000),
                     "margins_mm": _object(_SIDES, additional=False)}, additional=False),
    "body": _object({
        "style_ids": {"$ref": "#/$defs/styleIds"},
        "property_style_ids": _object({key: {"$ref": "#/$defs/styleIds"} for key in _BODY_SCOPE}, additional=False),
        "font": _NONBLANK, "fonts": _object({slot: _NONBLANK for slot in ("eastAsia", "ascii", "hAnsi", "cs")}, additional=False),
        "size_pt": _number(200, positive=True), "line_spacing": _number(200, positive=True),
        "pdf_region_mm": _object(_SIDES, required=_SIDES, additional=False),
    }, additional=False),
    "required_headings": {"type": "array", "items": _NONBLANK},
    "references": _object({
        "heading": _NONBLANK, "heading_after_lines": _number(200),
        "entry_style_ids": {"$ref": "#/$defs/styleIds"}, "entry_hanging_chars": _number(200),
        "entry_hanging_tolerance_chars": _number(200), "citation_order": {"enum": ["ascending", "none"]},
        "citation_start": {"type": "integer", "minimum": 1, "maximum": 100000}, "citation_unique": {"type": "boolean"},
    }, additional=False),
    "fields": _object({
        "required": {"type": "array", "items": {"enum": list(_FIELD_NAMES)}},
        "expected": _object({key: {**_NONBLANK, "maxLength": 120} for key in _FIELD_NAMES}, additional=False),
        "review_signatures": {"type": "boolean"},
        "missing_policy": {"enum": ["review", "fail_when_complete"], "default": "review"},
    }, additional=False),
})
_PROFILE = _object({
    "id": _IDENTIFIER, "name": {**_NONBLANK, "maxLength": 120}, "version": {"type": "integer", "minimum": 1, "default": 1},
    "description": {"type": "string", "maxLength": 4000, "default": ""},
    "plugins": {"type": "array", "minItems": 1, "uniqueItems": True,
                "prefixItems": [{"const": "docx-package"}], "items": _IDENTIFIER},
    "settings": {"$ref": "#/$defs/settings"}, "kinds": {"type": "array", "minItems": 1, "items": {"enum": KINDS}},
    "school": {"type": ["object", "null"]}, "requirements": {"type": "array", "items": {"$ref": "#/$defs/requirement"}},
    "scoped_rules": {"type": "array", "maxItems": 1500, "items": {"$ref": "#/$defs/requirement"}},
    "scope_bindings": {"type": "object"}, "scope_binding": {"type": "object"}, "source_profile_sha256": _HASH,
}, required=("id", "name", "plugins"))
_PROFILE["allOf"] = [{
    "if": {"required": ["school"], "properties": {"school": {"type": "object"}}},
    "then": {"properties": {"requirements": {"maxItems": 1500}}},
    "else": {"properties": {"requirements": {"maxItems": 500}}},
}]

_CHECK = _object({
    "rule_id": _TEXT, "status": {"enum": CHECK_STATES}, "kind": {"enum": ["format", "integrity", "content"]},
    "target": _TEXT, "location": {"type": ["string", "null"]}, "source": _SOURCE,
    "expected": {}, "actual": {}, "reason": _TEXT, "label": _TEXT,
    "plugin": _TEXT, "check_id": _TEXT, "requirement_id": _TEXT,
    "observed_rule_ids": {"type": "array", "items": _TEXT}, "observed_check_ids": {"type": "array", "items": _TEXT},
    "scope_style_ids": {"anyOf": [{"$ref": "#/$defs/styleIds"}, {"type": "null"}]},
    "scope_section_indices": {"anyOf": [_SECTION_INDICES, {"type": "null"}]}, "section_index": {"type": "integer", "minimum": 1},
    "parameters": {"type": "object"}, "requirement_ids": {"type": "array", "items": _TEXT},
    "scope_binding_status": {"enum": ["bound", "unbound"]}, "source_scope_style_ids": {"$ref": "#/$defs/styleIds"},
    "source_scope_section_indices": _SECTION_INDICES, "source_parameters": {"type": "object"},
    "excluded": {"type": "boolean"}, "exclusion_reason": _TEXT,
}, required=("rule_id", "status"))
_ISSUE = _object({
    "rule_id": _TEXT, "level": {"enum": ["error", "warning", "manual"]}, "message": _TEXT,
    "location": {"type": ["string", "null"]}, "expected": {}, "actual": {}, "source": _SOURCE,
    "plugin": _TEXT, "category": _TEXT,
    "check_ids": {"type": "array", "items": _TEXT}, "requirement_ids": {"type": "array", "items": _TEXT},
    "school_sources": {"type": "array", "items": _SOURCE},
}, required=("rule_id", "level", "message"))
_COUNTS = _object({level: {"type": "integer", "minimum": 0} for level in ("error", "warning", "manual")},
                  required=("error", "warning", "manual"), additional=False)
_EXTRACTION = _object({
    "format": {"enum": ["docx", "pdf", "txt", "md", "json"]}, "complete": {"type": "boolean"},
    "requires_review": {"type": "boolean"}, "warnings": {"type": "array", "items": _TEXT},
    "encoding": {"type": ["string", "null"]}, "schema": {"type": ["string", "null"]}, "ocr": {"type": ["object", "null"]},
    "page_count": {"type": "integer", "minimum": 0}, "processed_pages": {"type": "integer", "minimum": 0},
    "entry_count": {"type": "integer", "minimum": 0}, "pages": {"type": "array", "items": {"type": "object"}},
    "methods": {"type": "array", "items": _TEXT},
    "ocr_review": _object({
        **{key: {"type": "integer", "minimum": 0} for key in
           ("observation_count", "disagreement_count", "consistent_count", "not_checked_count")},
        "truncated": {"type": "boolean"}, "observations": {"type": "array", "maxItems": 40, "items": {"type": "object"}},
    }, required=("observation_count", "disagreement_count", "consistent_count", "not_checked_count", "truncated", "observations")),
}, required=("format", "complete", "requires_review", "warnings", "page_count", "processed_pages", "entry_count", "pages", "methods"))
_ENGINE = _object({
    "id": _IDENTIFIER, "status": {"enum": ["completed", "incomplete", "failed"]},
    "duration_ms": {"type": "integer", "minimum": 0}, "error": _TEXT,
    "evidence": {"type": "object"}, "checks": {"type": "array", "items": {"$ref": "#/$defs/check"}},
}, required=("id", "status", "duration_ms"))
_REPORT = _object({
    "schema_version": {"const": 3}, "profile_id": _IDENTIFIER, "profile_snapshot": {"$ref": "#/$defs/profile"},
    "profile_sha256": _HASH, "kind": {"enum": KINDS}, "input_format": {"enum": ["docx", "pdf", "txt", "md", "json"]},
    "document_extraction": {"anyOf": [{"$ref": "#/$defs/extraction"}, {"type": "null"}]},
    "created_at": {"type": "string", "format": "date-time"},
    "status": {"enum": ["passed", "needs_changes", "review_required", "incomplete"]},
    "counts": {"$ref": "#/$defs/counts"}, "document_counts": {"$ref": "#/$defs/counts"},
    "execution_errors": {"type": "integer", "minimum": 0}, "issues": {"type": "array", "items": {"$ref": "#/$defs/issue"}},
    "engines": {"type": "array", "items": {"$ref": "#/$defs/engine"}}, "input_sha256": _HASH,
    "input_unchanged": {"type": "boolean"}, "pdf_sha256": {"anyOf": [_HASH, {"type": "null"}]},
    "pdf_unchanged": {"type": ["boolean", "null"]}, "rules_unchanged": {"type": "boolean"},
    "manual_items_count_as_pass": {"const": False}, "filename": _TEXT,
    "original_unchanged": {"type": "boolean"}, "original_pdf_unchanged": {"type": "boolean"},
    "revision_of_job_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}, "repair": {"type": "object"},
    "coverage": _object({
        "checks": {"type": "array", "items": {"$ref": "#/$defs/check"}},
        "summary": _object({state: {"type": "integer", "minimum": 0} for state in CHECK_STATES}, required=CHECK_STATES, additional=False),
        "format_checks": {"type": "integer", "minimum": 0}, "complete": {"type": "boolean"},
        "scope": {"enum": ["school_requirements", "configured_attributes"]},
    }, required=("checks", "summary", "format_checks", "complete", "scope")),
}, required=("schema_version", "profile_id", "profile_snapshot", "profile_sha256", "kind", "input_format", "document_extraction",
             "created_at", "status", "counts", "document_counts", "execution_errors", "issues", "engines", "coverage",
             "input_sha256", "input_unchanged", "pdf_sha256", "pdf_unchanged", "rules_unchanged", "manual_items_count_as_pass"))
_PLUGIN_RESULT = _object({
    "issues": {"type": "array", "items": {"$ref": "#/$defs/issue"}}, "evidence": {"type": "object"},
    "status": {"enum": ["completed", "incomplete"]}, "checks": {"type": "array", "items": {"$ref": "#/$defs/check"}},
}, required=("issues", "evidence", "status", "checks"))

_DEFINITIONS = {"styleIds": _STYLE_IDS, "requirement": _REQUIREMENT, "settings": _SETTINGS, "profile": _PROFILE,
                "check": _CHECK, "issue": _ISSUE, "counts": _COUNTS, "extraction": _EXTRACTION, "engine": _ENGINE}
_CONTRACTS = {
    "profile": (1, "Formatly 规则方案", _PROFILE, ("styleIds", "requirement", "settings")),
    "requirement": (1, "Formatly 学校要求条款", _REQUIREMENT, ("styleIds",)),
    "report": (3, "Formatly 检测报告", _REPORT, tuple(_DEFINITIONS)),
    "check": (1, "Formatly 逐规则检查项", _CHECK, ("styleIds",)),
    "plugin-result": (1, "Formatly 插件执行结果", _PLUGIN_RESULT, ("styleIds", "issue", "check")),
    "scope-bindings": (1, "Formatly 原稿范围确认", {}, ()),
}


def catalog() -> dict:
    """List current contracts without importing a validator or accessing storage."""
    return {"schema_version": 1, "dialect": DIALECT, "schemas": [
        {"name": name, "title": title, "version": version, "id": f"urn:formatly:schema:{name}:{version}",
         "url": f"/api/schemas/{name}.json"} for name, (version, title, _, _) in _CONTRACTS.items()
    ]}


def schema(name: str) -> dict:
    """Return an independent, offline-validatable schema; unknown names raise KeyError."""
    version, title, shape, definitions = _CONTRACTS[name]
    if name == "scope-bindings":
        from .document_scopes import binding_schema
        return deepcopy({"$schema": DIALECT, "$id": f"urn:formatly:schema:{name}:{version}", "title": title, **binding_schema()})
    return deepcopy({"$schema": DIALECT, "$id": f"urn:formatly:schema:{name}:{version}", "title": title,
                     **shape, "$defs": {key: _DEFINITIONS[key] for key in definitions}})
