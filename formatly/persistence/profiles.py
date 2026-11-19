"""Validated, versioned profiles. User profiles never mutate built-in profiles."""
from __future__ import annotations

import builtins
import json
from pathlib import Path
import re
from typing import Any, cast

from ..files import write_json
from ..privacy import redact_local_paths
from ..plugins.academic_rules import normalize_style_ids, validate_academic_settings, validate_academic_value, ACADEMIC_TARGETS
from ..plugins.structure_rules import validate_structure_settings
from .school_compiler import SCOPE_FIELDS, rule_settings, target_plugin, validate_requirement_scope

BUILTINS = {
    "academic": {"id": "academic", "name": "论文与报告 · 排版检查", "version": 1,
                 "description": "检查A4纸张和单栏版式；正文、标题与分节参数请按学校要求设置，正文段落须指定样式范围。",
                 "kinds": ["thesis", "intern"],
                 "plugins": ["docx-package", "generic-format", "academic-format", "document-fields"],
                 "settings": {"page": {"width_mm": 210, "height_mm": 297, "tolerance_mm": 1}, "section": {"columns": 1}}},
    "generic": {"id": "generic", "name": "通用论文 · 基础预检", "version": 1,
                "description": "按输入格式检查文档完整性、可证明的A4页面属性和材料字段；文本格式不推断排版，不预设学校规范。",
                "plugins": ["docx-package", "generic-format", "document-fields"],
                "settings": {"page": {"width_mm": 210, "height_mm": 297, "tolerance_mm": 1},
                             "required_headings": [], "body": {}}},
    "certificate": {"id": "certificate", "name": "实习证明 · 基础预检", "version": 1,
                    "description": "检查基础页面属性、证明字段与人工签章事项；不证明签章或材料真实性。",
                    "kinds": ["certificate"], "plugins": ["docx-package", "generic-format", "document-fields"],
                    "settings": {"page": {"width_mm": 210, "height_mm": 297},
                                 "fields": {"required": ["name", "organization", "start_date", "end_date"], "review_signatures": True}}},
    "school-specific": {"id": "school-specific", "name": "学校专项 · 外部引擎", "version": 1,
                         "description": "依赖可选外部专项引擎做更深核验；未安装时请改用「学校要求」生成方案或预置方案。适用范围由方案内容决定。",
                         "plugins": ["docx-package", "legacy-school"], "kinds": ["thesis", "intern"], "settings": {}},
}

BODY_SCOPE_PROPERTIES = {"font", "size_pt", "line_spacing", "fonts.eastAsia", "fonts.ascii", "fonts.hAnsi", "fonts.cs"}
REFERENCE_SETTINGS = {
    "heading", "heading_after_lines", "entry_style_ids", "entry_hanging_chars",
    "entry_hanging_tolerance_chars", "citation_order", "citation_start", "citation_unique",
}


def _bounded_number(value: object, minimum: float, maximum: float, *, exclusive_minimum=False) -> bool:
    if type(value) not in (int, float):
        return False
    numeric = cast(int | float, value)
    return (minimum < numeric if exclusive_minimum else minimum <= numeric) and numeric <= maximum


def _bounded_integer(value: object, minimum: int, maximum: int) -> bool:
    if type(value) is not int:
        return False
    numeric = cast(int, value)
    return minimum <= numeric <= maximum


def validate_style_ids(value: object, label="正文样式范围", *, allow_empty=True) -> list[str]:
    if not isinstance(value, list) or len(value) > 100 or (not allow_empty and not value):
        raise ValueError(label + "须为最多100项的非空样式ID组成的数组")
    normalized: list[str] = []
    for raw_style in value:
        if not isinstance(raw_style, str) or not raw_style.strip() or len(raw_style) > 120:
            raise ValueError(label + "须为最多100项的非空样式ID组成的数组")
        normalized.append(raw_style.strip())
    return sorted(set(normalized))


def validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict):
        raise ValueError("方案必须为JSON对象")
    if not isinstance(profile.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", profile["id"]):
        raise ValueError("方案ID须以小写字母开头，仅含小写字母、数字和连字符，最多64字符")
    if not isinstance(profile.get("name"), str) or not profile["name"].strip() or len(profile["name"]) > 120:
        raise ValueError("方案名称必填且最多120字符")
    if not isinstance(profile.get("description", ""), str) or len(profile.get("description", "")) > 4000:
        raise ValueError("方案说明须为文本且最多4000字符")
    plugins = profile.get("plugins")
    if not isinstance(plugins, list) or not plugins or any(not isinstance(p, str) for p in plugins) or len(set(plugins)) != len(plugins):
        raise ValueError("plugins须为非空且不重复的插件ID数组")
    if plugins[0] != "docx-package":
        raise ValueError("docx-package完整性检查必须作为第一个插件")
    settings = profile.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("settings须为对象")
    validate_academic_settings(settings)
    validate_structure_settings(settings)
    if "paragraph" in settings:
        paragraph: dict[str, Any] = dict(settings["paragraph"])
        if "style_ids" in paragraph:
            paragraph["style_ids"] = normalize_style_ids(paragraph["style_ids"], "paragraph.style_ids")
        if "property_style_ids" in paragraph:
            paragraph["property_style_ids"] = {key: normalize_style_ids(value, "paragraph.property_style_ids." + key)
                                               for key, value in paragraph["property_style_ids"].items()}
        settings = {**settings, "paragraph": paragraph}
    page = settings.get("page", {})
    body = settings.get("body", {})
    references = settings.get("references", {})
    if not isinstance(page, dict) or not isinstance(body, dict):
        raise ValueError("page和body须为对象")
    if not isinstance(references, dict):
        raise ValueError("references须为对象")
    if set(page) - {"width_mm", "height_mm", "tolerance_mm", "margins_mm"}:
        raise ValueError("page包含不支持的字段，请核对规则参数名称")
    if set(body) - {"style_ids", "property_style_ids", "font", "fonts", "size_pt", "line_spacing", "pdf_region_mm"}:
        raise ValueError("body包含不支持的字段，请核对规则参数名称")
    if set(references) - REFERENCE_SETTINGS:
        raise ValueError("references包含不支持的字段，请核对规则参数名称")
    for key in ("width_mm", "height_mm"):
        if key in page and not _bounded_number(page[key], 0, 2000, exclusive_minimum=True):
            raise ValueError(f"page.{key}须为大于0且不超过2000的数字")
    if "tolerance_mm" in page and not _bounded_number(page["tolerance_mm"], 0, 2000):
        raise ValueError("page.tolerance_mm须为0至2000的数字")
    margins = page.get("margins_mm", {})
    if not isinstance(margins, dict) or set(margins) - {"top", "bottom", "left", "right"}:
        raise ValueError("页边距仅支持top/bottom/left/right")
    if any(not _bounded_number(value, 0, 200) for value in margins.values()):
        raise ValueError("页边距须为0至200毫米")
    if "pdf_region_mm" in body:
        region = body["pdf_region_mm"]
        if (not isinstance(region, dict) or set(region) != {"top", "bottom", "left", "right"}
                or any(not _bounded_number(value, 0, 200) for value in region.values())):
            raise ValueError("body.pdf_region_mm 须明确设置 top/bottom/left/right 四个距页面边缘0至200毫米的正文检查范围")
    headings = settings.get("required_headings", [])
    if not isinstance(headings, list) or any(not isinstance(v, str) or not v.strip() for v in headings):
        raise ValueError("required_headings须为非空标题文本组成的数组")
    if "style_ids" in body:
        body = {**body, "style_ids": validate_style_ids(body["style_ids"], "body.style_ids")}
    property_scopes = body.get("property_style_ids", {})
    if not isinstance(property_scopes, dict) or set(property_scopes) - BODY_SCOPE_PROPERTIES:
        raise ValueError("body.property_style_ids包含不支持的正文属性")
    if "property_style_ids" in body:
        body = {**body, "property_style_ids": {key: validate_style_ids(style_ids, "body.property_style_ids." + key)
                                              for key, style_ids in property_scopes.items()}}
    if "body" in settings:
        settings = {**settings, "body": body}
    font = body.get("font")
    if "font" in body and (not isinstance(font, str) or not font.strip()):
        raise ValueError("body.font须为非空字体名称")
    fonts = body.get("fonts", {})
    if (not isinstance(fonts, dict) or set(fonts) - {"eastAsia", "ascii", "hAnsi", "cs"}
            or any(not isinstance(value, str) or not value.strip() for value in fonts.values())):
        raise ValueError("body.fonts仅支持eastAsia/ascii/hAnsi/cs非空字体名称")
    for key in ("size_pt", "line_spacing"):
        if key in body and not _bounded_number(body[key], 0, 200, exclusive_minimum=True):
            raise ValueError(f"body.{key}须为大于0且不超过200的数字")
    if "heading" in references and (not isinstance(references["heading"], str) or not references["heading"].strip()):
        raise ValueError("references.heading须为非空标题文本")
    for key in ("heading_after_lines", "entry_hanging_chars", "entry_hanging_tolerance_chars"):
        if key in references and not _bounded_number(references[key], 0, 200):
            raise ValueError(f"references.{key}须为0至200的数字")
    if "entry_style_ids" in references:
        references = {**references, "entry_style_ids": validate_style_ids(references["entry_style_ids"], "references.entry_style_ids")}
    if "citation_order" in references and references["citation_order"] not in {"ascending", "none"}:
        raise ValueError("references.citation_order仅支持ascending或none")
    if "citation_start" in references and not _bounded_integer(references["citation_start"], 1, 100000):
        raise ValueError("references.citation_start须为1至100000的整数")
    if "citation_unique" in references and type(references["citation_unique"]) is not bool:
        raise ValueError("references.citation_unique须为布尔值")
    if "allow_repeated_citations" in references and type(references["allow_repeated_citations"]) is not bool:
        raise ValueError("references.allow_repeated_citations须为布尔值")
    if "references" in settings:
        settings = {**settings, "references": references}
    kinds = profile.get("kinds", ["thesis", "intern", "certificate"])
    if not isinstance(kinds, list) or not kinds or any(kind not in {"thesis", "intern", "certificate"} for kind in kinds):
        raise ValueError("kinds须为thesis/intern/certificate组成的非空数组")
    version = profile.get("version", 1)
    if type(version) is not int or version < 1:
        raise ValueError("version须为正整数")
    school = profile.get("school")
    if school is not None and not isinstance(school, dict):
        raise ValueError("school须为学校依据元数据对象")
    if school is not None and "source_profile_id" in school and (
            not isinstance(school["source_profile_id"], str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", school["source_profile_id"])
            or school["source_profile_id"] == profile["id"]):
        raise ValueError("学校副本来源须为有效方案ID")
    requirements = profile.get("requirements", [])
    maximum = 1500 if school is not None else 500
    if not isinstance(requirements, list) or len(requirements) > maximum:
        raise ValueError(f"requirements须为最多{maximum}项的数组")
    ids = set()
    for requirement in requirements:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("id"), str) or not requirement["id"] or requirement["id"] in ids:
            raise ValueError("要求项须有非空且不重复的id")
        ids.add(requirement["id"])
        if requirement.get("kind") not in {"thesis", "intern", "certificate"}:
            raise ValueError("要求项kind无效")
        if requirement.get("mode") not in {"automatic", "manual"} or type(requirement.get("confirmed")) is not bool:
            raise ValueError("要求项须明确mode与confirmed")
        if type(requirement.get("excluded", False)) is not bool:
            raise ValueError("要求项excluded须为布尔值")
        if not isinstance(requirement.get("exclusion_reason", ""), str):
            raise ValueError("要求项排除理由须为文本")
        if requirement.get("excluded") and (not requirement["confirmed"] or not requirement.get("exclusion_reason", "").strip()):
            raise ValueError("排除要求须明确确认并填写排除理由")
        if not isinstance(requirement.get("target"), str) or not requirement["target"]:
            raise ValueError("要求项target必填")
        if (requirement["target"] in ACADEMIC_TARGETS and requirement.get("confirmed")
                and requirement["mode"] == "automatic" and not requirement.get("excluded")):
            validate_academic_value(requirement["target"], requirement.get("expected"))
        if "scope_style_ids" in requirement:
            validate_style_ids(requirement["scope_style_ids"], "要求项scope_style_ids")
        validate_requirement_scope(requirement)
    requirements = [{**requirement,
                     **({"scope_style_ids": validate_style_ids(requirement["scope_style_ids"])} if "scope_style_ids" in requirement else {}),
                     **({"expected": validate_style_ids(requirement["expected"], allow_empty=False)}
                        if requirement["target"] == "body.style_ids" and requirement.get("confirmed") and requirement["mode"] == "automatic" and not requirement.get("excluded") else {})}
                    for requirement in requirements]
    encoded = json.dumps(profile, allow_nan=False)
    if len(encoded.encode("utf-8")) > (2 * 1024 * 1024 if school is not None else 128 * 1024):
        raise ValueError("规则方案过大")
    result = {"id": profile["id"], "name": profile["name"].strip(), "version": version,
              "description": profile.get("description", ""), "plugins": plugins, "settings": settings,
              "kinds": list(dict.fromkeys(kinds))}
    if school is not None:
        result["school"] = school
    if requirements:
        result["requirements"] = requirements
    if "scoped_rules" in profile:
        rules = profile["scoped_rules"]
        if not isinstance(rules, list) or len(rules) > maximum:
            raise ValueError("范围规则须为有界数组")
        by_id = {item["id"]: item for item in requirements}
        seen_rules = set()
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("id") in seen_rules:
                raise ValueError("范围规则标识无效或重复")
            original = by_id.get(rule.get("id"))
            if (original is None or not original.get("confirmed") or original.get("excluded") or original.get("mode") != "automatic"
                    or any(rule.get(key) != original.get(key) for key in ("kind", "target", "expected", *SCOPE_FIELDS))
                    or rule.get("plugin_id") != target_plugin(original["target"]) or rule["plugin_id"] not in plugins):
                raise ValueError("范围规则必须对应已确认的原始要求及其消费插件")
            seen_rules.add(rule["id"])
            local_settings = rule_settings(rule)
            # A multi-value target has no single settings projection to validate.
            # Validate its isolated configuration with the same complete guards.
            validate_profile({"id": "scoped-value", "name": "范围参数校验", "plugins": ["docx-package", rule["plugin_id"]],
                              "settings": local_settings})
        result["scoped_rules"] = json.loads(json.dumps(rules, ensure_ascii=False, allow_nan=False))
    for key in ("scope_bindings", "scope_binding", "source_profile_sha256"):
        if key in profile:
            result[key] = json.loads(json.dumps(profile[key], ensure_ascii=False, allow_nan=False))
    return result


class PendingSchoolPublication(ValueError):
    """A compiled profile batch is not yet committed by its school."""


class ProfileStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "profiles"
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, profile_id: str) -> dict:
        if profile_id in BUILTINS:
            return json.loads(json.dumps(BUILTINS[profile_id]))
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", profile_id):
            raise ValueError("无效方案ID")
        path = self.root / (profile_id + ".json")
        if not path.is_file():
            raise ValueError(f"规则方案不存在: {profile_id}")
        return self._read_custom(path)

    def _read_custom(self, path: Path) -> dict:
        profile = validate_profile(json.loads(path.read_text(encoding="utf-8-sig")))
        if profile["id"] != path.stem:
            raise ValueError(f"方案ID {profile['id']} 与文件名 {path.name} 不一致")
        if profile["id"] in BUILTINS:
            raise ValueError("自定义方案不能覆盖只读内置方案")
        self._check_school_publication(profile)
        return profile

    def _publication_profiles(self, identity: str, version: object) -> list[dict] | None:
        publication = self.root.parent / "schools" / identity / "publications" / f"{version}.json"
        if not publication.is_file():
            return None
        from .schools import MAX_SCHOOL_BYTES
        if publication.stat().st_size > 8 * MAX_SCHOOL_BYTES:
            raise ValueError("学校方案发布记录过大，请恢复备份")
        published = json.loads(publication.read_text(encoding="utf-8"))
        if (not isinstance(published, dict) or not isinstance(published.get("profiles"), list)
                or not 1 <= len(published["profiles"]) <= 3
                or any(not isinstance(item, dict) for item in published["profiles"])):
            raise ValueError("学校方案发布记录损坏，请恢复备份")
        return published["profiles"]

    def _check_school_publication(self, profile: dict, *, allow_staged=False) -> None:
        school = profile.get("school") or {}
        identity, version = school.get("id"), school.get("version")
        if (not isinstance(identity, str) or not re.fullmatch(r"school-[a-f0-9]{16}", identity)
                or type(version) is not int or version < 1):
            return
        directory = self.root.parent / "schools" / identity
        published = self._publication_profiles(identity, version)
        if published is None:
            return  # A portable profile import has no local publication intent.
        from .schools import MAX_SCHOOL_BYTES, SchoolStore
        try:
            source_id = school.get("source_profile_id", profile["id"])
            expected = next((item for item in published if item.get("id") == source_id), None)
            if expected is None:
                raise PendingSchoolPublication("学校方案不属于发布记录，请通过复制入口保存新方案")
            is_copy = source_id != profile["id"]
            if "source_profile_id" in school:
                expected = {**expected, **{key: profile[key] for key in ("id", "name", "description", "version")},
                            "school": {**expected.get("school", {}), "source_profile_id": source_id}}
            if expected != profile:
                raise ValueError("学校方案与发布快照不一致，请重新确认要求")
            # Only exact original snapshots may be staged before the school
            # pointer commits. Copies require a fully published source below.
            if allow_staged and not is_copy:
                return
            current = SchoolStore(self.root.parent).get(identity)
            if current["version"] < version:
                raise PendingSchoolPublication("学校方案尚未完整发布，请重试确认学校要求")
            revision_path = directory / "revisions" / f"{version}.json"
            if not revision_path.is_file() or revision_path.stat().st_size > MAX_SCHOOL_BYTES:
                raise PendingSchoolPublication("学校方案尚未完整发布，请重试确认学校要求")
            revision = json.loads(revision_path.read_text(encoding="utf-8"))
            if (not isinstance(revision, dict) or revision.get("id") != identity or revision.get("version") != version
                    or revision.get("status") not in {"draft", "confirmed"}
                    or not isinstance(revision.get("profiles"), list)
                    or any(not isinstance(item, str) for item in revision["profiles"])):
                raise ValueError("学校方案确认记录损坏，请恢复备份")
            if revision.get("status") != "confirmed" or source_id not in revision.get("profiles", []):
                raise PendingSchoolPublication("学校方案尚未完整发布，请重试确认学校要求")
        except KeyError as exc:
            raise PendingSchoolPublication("学校方案尚未完整发布，请重试确认学校要求") from exc

    def _scan(self) -> tuple[builtins.list[dict], builtins.list[dict]]:
        profiles = [self.get(key) for key in BUILTINS]
        errors = []
        for path in sorted(self.root.glob("*.json")):
            try:
                profiles.append(self._read_custom(path))
            except PendingSchoolPublication:
                continue
            except (OSError, ValueError, RecursionError) as exc:
                errors.append({"id": path.stem, "file": path.name, "message": redact_local_paths(str(exc))})
        return profiles, errors

    def list(self) -> builtins.list[dict]:
        return self._scan()[0]

    def list_errors(self) -> builtins.list[dict]:
        return self._scan()[1]

    def save(self, value: dict) -> dict:
        profile = validate_profile(value)
        if profile["id"] in BUILTINS:
            raise ValueError("内置方案只读；请使用新的ID保存自定义方案")
        published_id = re.fullmatch(r"(school-[a-f0-9]{16})-v([1-9][0-9]*)-(?:thesis|intern|certificate)", profile["id"])
        if published_id:
            originals = self._publication_profiles(published_id[1], published_id[2])
            expected = next((item for item in originals or [] if item.get("id") == profile["id"]), None)
            if expected is not None and expected != profile:
                raise ValueError("已发布学校方案只读，请用新的ID保存副本")
        self._check_school_publication(profile, allow_staged=True)
        write_json(self.root / (profile["id"] + ".json"), profile)
        return profile

