"""Input-bound scope choices and bounded, temporary manuscript previews."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from threading import RLock
import time
import uuid

from ..documents.docx_semantics import active_sections, paragraph_style, read_docx_content
from ..documents.style_catalog import paragraph_style_catalog
from ..files import MAX_FILE_BYTES, atomic_write, read_docx, safe_child, write_json
from ..persistence.locks import write_lock

MAX_BINDING_BYTES = 1024 * 1024


def profile_digest(profile: dict) -> str:
    return hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def document_scope_digest(path: Path) -> str:
    """Fingerprint visible text, styles and section boundaries independently of formatting."""
    package = read_docx(path)
    document = package["document"]
    paragraphs = {paragraph.element: paragraph for paragraph in read_docx_content(
        document, package.get("styles"), numbering=package.get("numbering"), styles_reason=package.get("styles_reason", "")).paragraphs}
    sections = set(active_sections(document))
    sequence = []
    for node in document.iter():
        if node in paragraphs:
            paragraph = paragraphs[node]
            sequence.append(["paragraph", paragraph.index, paragraph_style(node, package.get("styles")), paragraph.text])
        elif node in sections:
            sequence.append(["section"])
    return profile_digest({"sequence": sequence})


def binding_schema() -> dict:
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "input_sha256", "profile_sha256", "kind", "items"],
        "properties": {"schema_version": {"const": 1}, "input_sha256": digest, "profile_sha256": digest,
            "kind": {"enum": ["thesis", "intern", "certificate"]}, "items": {"type": "array", "maxItems": 1500,
                "items": {"oneOf": [
                    {"type": "object", "additionalProperties": False, "required": ["requirement_id", "status", key],
                     "properties": {"requirement_id": {"type": "string", "minLength": 1, "maxLength": 200},
                         "status": {"const": "bound"}, key: {"type": "array", "minItems": 1, "maxItems": 100,
                         "uniqueItems": True, "items": values}}}
                    for key, values in (("style_ids", {"type": "string", "minLength": 1, "maxLength": 120}),
                                        ("section_indices", {"type": "integer", "minimum": 1, "maximum": 1000}))
                ] + [{"type": "object", "additionalProperties": False, "required": ["requirement_id", "status", "reason"],
                      "properties": {"requirement_id": {"type": "string", "minLength": 1, "maxLength": 200},
                          "status": {"const": "unbound"}, "reason": {"type": "string", "pattern": r"\S", "maxLength": 500}}}]}}}}


def scope_requirements(profile: dict, kind: str) -> list[dict]:
    """Describe selectors without equating a template's IDs to a draft's roles."""
    from .profile_capabilities import profile_fields
    metadata = {item["target"]: item for item in profile_fields().get("school_targets", [])}
    result = []
    requirements = profile.get("requirements", [])
    for requirement in requirements:
        if (requirement.get("kind") != kind or not requirement.get("confirmed") or requirement.get("excluded")
                or requirement.get("mode") != "automatic" or requirement.get("expected") is False):
            continue
        target = requirement["target"]
        scope_type = metadata.get(target, {}).get("scope")
        if (target.startswith("body.") and target != "body.style_ids") or target.startswith("paragraph."):
            scope_type = "styles"
        elif target.startswith("structure.captions."):
            scope_type = "styles"
        elif target.startswith("structure.page_numbers.") or requirement.get("scope_section_indices"):
            scope_type = "sections"
        if (scope_type == "sections" and target.startswith(("page.", "section."))
                and not requirement.get("scope_section_indices") and not requirement.get("parameters", {}).get("section_indices")):
            continue
        if scope_type not in {"styles", "sections"}:
            continue
        result.append({"id": requirement["id"], "target": target, "label": requirement.get("label") or target,
            "expected": requirement.get("expected"), "scope_type": scope_type,
            "source_scope_style_ids": requirement.get("source_scope_style_ids", requirement.get("scope_style_ids", [])),
            "source_scope_section_indices": requirement.get("source_scope_section_indices", requirement.get("scope_section_indices", [])),
            "source_excerpt": requirement.get("source_excerpt") or "", "source_locator": requirement.get("source_locator") or ""})
    if not requirements:
        from ..plugins.academic_rules import configured_academic_values
        from ..plugins.structure_rules import configured_structure_values
        settings = profile.get("settings", {})
        configured = [("body." + key, value) for key, value in settings.get("body", {}).items()
                      if key in {"font", "size_pt", "line_spacing"}]
        configured += [("body.fonts." + key, value) for key, value in settings.get("body", {}).get("fonts", {}).items()]
        configured += list(configured_academic_values(settings)) + list(configured_structure_values(settings))
        for target, expected in configured:
            scope_type = "styles" if target.startswith(("body.", "paragraph.", "structure.captions.")) else (
                "sections" if target.startswith("structure.page_numbers.") else None)
            if scope_type and expected is not False:
                result.append({"id": "setting:" + target, "target": target, "label": metadata.get(target, {}).get("label", target),
                               "expected": expected, "scope_type": scope_type, "source_excerpt": "", "source_locator": "规则方案"})
    return result


def scope_capabilities(profile: dict, kind: str, input_format: str) -> dict:
    items = scope_requirements(profile, kind)
    return {"required": bool(items) and bool(profile.get("school")) and input_format == "docx",
            "supported": input_format == "docx", "items": items}


def section_catalog(package: dict, offset=0, limit=10) -> dict:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("分节分页参数无效")
    document = package["document"]
    sections = active_sections(document)
    positions = {node: index for index, node in enumerate(document.iter())}
    paragraphs = read_docx_content(document, package.get("styles"), numbering=package.get("numbering"),
                                    styles_reason=package.get("styles_reason", "")).paragraphs
    items, previous = [], -1
    for index, section in enumerate(sections, 1):
        end = positions[section]
        visible = [paragraph for paragraph in paragraphs if previous < positions[paragraph.element] <= end and paragraph.text.strip()]
        items.append({"index": index, "label": f"第 {index} 节", "paragraph_count": len(visible),
                      "samples": [{"text": paragraph.text[:200], "location": f"XML段{paragraph.index}"} for paragraph in visible[:3]]})
        previous = end
    return {"items": items[offset:offset + limit], "total": len(items), "offset": offset, "limit": limit}


def derive_profile(profile: dict, kind: str, path: Path, bindings: dict | None) -> tuple[dict, dict | None]:
    """Validate selectors against actual input, then compile only this execution copy."""
    items = scope_requirements(profile, kind)
    digest = profile_digest(profile)
    input_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    selections: dict[str, dict] = {}
    if bindings is not None:
        if (not isinstance(bindings, dict) or set(bindings) != {"schema_version", "input_sha256", "profile_sha256", "kind", "items"}
                or type(bindings.get("schema_version")) is not int or bindings["schema_version"] != 1
                or bindings.get("input_sha256") != input_digest or bindings.get("profile_sha256") != digest
                or bindings.get("kind") != kind or not isinstance(bindings.get("items"), list)
                or len(bindings["items"]) > 1500
                or len(json.dumps(bindings, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BINDING_BYTES):
            raise ValueError("原稿范围确认与当前输入、方案或材料类型不一致，请重新预览")
        if path.suffix != ".docx":
            raise ValueError("原稿样式／分节范围确认目前仅支持 DOCX")
        expected_ids = {item["id"] for item in items}
        for value in bindings["items"]:
            if (not isinstance(value, dict) or not isinstance(value.get("requirement_id"), str)
                    or value["requirement_id"] not in expected_ids or value["requirement_id"] in selections):
                raise ValueError("范围确认包含未知或重复的要求")
            identity = value["requirement_id"]
            item = next(item for item in items if item["id"] == identity)
            key = "style_ids" if item["scope_type"] == "styles" else "section_indices"
            if value.get("status") == "unbound":
                if set(value) != {"requirement_id", "status", "reason"} or not isinstance(value.get("reason"), str) or not 0 < len(value["reason"].strip()) <= 500:
                    raise ValueError("暂不匹配须提供明确原因")
            elif value.get("status") == "bound":
                choices = value.get(key)
                if set(value) != {"requirement_id", "status", key} or not isinstance(choices, list) or not 1 <= len(choices) <= 100:
                    raise ValueError("范围确认须选择实际原稿中的样式或分节")
                if key == "style_ids" and any(not isinstance(choice, str) or not choice.strip() or len(choice) > 120 for choice in choices):
                    raise ValueError("样式标识无效")
                if key == "section_indices" and any(type(choice) is not int or not 1 <= choice <= 1000 for choice in choices):
                    raise ValueError("分节序号无效")
                if len(set(choices)) != len(choices):
                    raise ValueError("范围选择不能重复")
            else:
                raise ValueError("范围确认状态仅支持 bound 或 unbound")
            selections[identity] = deepcopy(value)
        if set(selections) != expected_ids:
            raise ValueError("请逐条确认范围，或明确选择暂不匹配")
        package = read_docx(path)
        all_styles = {paragraph_style(paragraph.element, package.get("styles"))
                      for paragraph in read_docx_content(package["document"], package.get("styles"),
                                                         numbering=package.get("numbering"), styles_reason=package.get("styles_reason", "")).paragraphs
                      if paragraph.text.strip()}
        section_count = len(active_sections(package["document"]))
        for selection in selections.values():
            if selection["status"] != "bound":
                continue
            if set(selection.get("style_ids", [])) - all_styles:
                raise ValueError("所选样式不存在或未被实际可见段落使用，请重新确认")
            if any(index > section_count for index in selection.get("section_indices", [])):
                raise ValueError("所选分节不存在，请重新确认")
    derived = deepcopy(profile)
    if profile.get("requirements"):
        for requirement in derived["requirements"]:
            descriptor = next((item for item in items if item["id"] == requirement["id"]), None)
            if descriptor is None:
                continue
            requirement.setdefault("source_scope_style_ids", deepcopy(requirement.get("scope_style_ids", [])))
            requirement.setdefault("source_scope_section_indices", deepcopy(requirement.get("scope_section_indices", [])))
            requirement.setdefault("source_parameters", deepcopy(requirement.get("parameters", {})))
            choice = selections.get(requirement["id"])
            requirement["scope_binding_status"] = "bound" if choice and choice["status"] == "bound" else "unbound"
            if choice and choice["status"] == "bound":
                if descriptor["scope_type"] == "styles":
                    requirement["scope_style_ids"] = list(choice["style_ids"])
                    if requirement["target"].startswith("structure.captions."):
                        requirement.setdefault("parameters", {})["style_ids"] = list(choice["style_ids"])
                else:
                    requirement["scope_section_indices"] = list(choice["section_indices"])
                    if requirement["target"].startswith("structure.page_numbers."):
                        requirement.setdefault("parameters", {})["section_indices"] = list(choice["section_indices"])
        if bindings is not None or profile.get("school") or profile.get("scoped_rules"):
            from ..persistence.school_compiler import compile_requirement_profile
            derived = compile_requirement_profile(derived, kind)
    elif bindings is not None:
        from .profile_capabilities import profile_fields
        from ..persistence.school_compiler import compile_requirement_profile
        metadata = {item["target"]: item for item in profile_fields().get("school_targets", [])}
        derived["requirements"] = []
        for descriptor in items:
            choice = selections.get(descriptor["id"])
            requirement = {"id": descriptor["id"], "kind": kind, "target": descriptor["target"],
                "label": descriptor["label"], "expected": descriptor["expected"], "confirmed": True,
                "mode": "automatic", "source_locator": "规则方案", "source_excerpt": "",
                "scope_binding_status": choice["status"] if choice else "unbound"}
            if descriptor["scope_type"] == "styles":
                requirement["scope_style_ids"] = choice.get("style_ids", []) if choice else []
            else:
                requirement["scope_section_indices"] = choice.get("section_indices", []) if choice else []
            if descriptor["target"].startswith("structure."):
                category = descriptor["target"].split(".")[1]
                group = derived["settings"]["structure"][category]
                keys = metadata.get(descriptor["target"], {}).get("parameters_schema", {}).get("properties", {})
                requirement["parameters"] = {key: deepcopy(value) for key, value in group.items() if key in keys}
                if choice and choice["status"] == "bound":
                    requirement["parameters"]["style_ids" if descriptor["scope_type"] == "styles" else "section_indices"] = list(choice.get("style_ids", choice.get("section_indices", [])))
            derived["requirements"].append(requirement)
        derived = compile_requirement_profile(derived, kind)
    return derived, deepcopy(bindings) if bindings is not None else None


class DocumentPreviewStore:
    """Short-lived input snapshots protected by a process-shared store lock."""
    def __init__(self, data_dir: Path, *, ttl_seconds=1200, max_previews=20, max_total_bytes=160 * 1024 * 1024):
        self.root = data_dir / "document-previews"
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.max_previews = max_previews
        self.max_total_bytes = max_total_bytes
        self._lock = RLock()

    def _directory(self, identity: str) -> Path:
        if not isinstance(identity, str) or re.fullmatch(r"[a-f0-9]{32}", identity) is None:
            raise ValueError("原稿预览标识无效")
        return safe_child(self.root, identity)

    def _metadata(self, identity: str) -> dict:
        directory = self._directory(identity)
        path = directory / "preview.json"
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("原稿预览已失效，请重新选择原稿")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
            raise ValueError("原稿预览记录损坏，请重新上传") from exc
        if (not isinstance(value, dict) or value.get("id") != identity
                or type(value.get("expires_timestamp")) not in {int, float}
                or not math.isfinite(value["expires_timestamp"])
                or value["expires_timestamp"] <= time.time()):
            raise ValueError("原稿预览已过期，请重新确认范围")
        input_path = directory / "input.docx"
        if not input_path.is_file() or not 0 < input_path.stat().st_size <= MAX_FILE_BYTES or hashlib.sha256(input_path.read_bytes()).hexdigest() != value.get("input_sha256"):
            raise ValueError("原稿预览快照已变化，请重新上传")
        return value

    def _cleanup(self) -> list[Path]:
        active = []
        for directory in self.root.iterdir():
            if (not directory.is_dir() or directory.is_symlink() or not directory.resolve().is_relative_to(self.root.resolve())
                    or re.fullmatch(r"[a-f0-9]{32}", directory.name) is None):
                continue
            try:
                self._metadata(directory.name)
            except (OSError, ValueError, TypeError, AttributeError):
                # Only random-ID, temporary preview directories are collected.
                shutil.rmtree(directory)
            else:
                active.append(directory)
        return active

    @contextmanager
    def temporary_document(self, document: bytes, filename: str):
        if not isinstance(document, bytes) or not 0 < len(document) <= MAX_FILE_BYTES:
            raise ValueError("文档为空或超过40MB限制")
        suffix = Path(filename).suffix.lower()
        # Use the data store's inherited permissions, just like job snapshots.
        # Windows can restrict a mode-0700 TemporaryDirectory to an identity
        # different from the service's restricted execution token.
        directory = safe_child(self.root.parent, "fs-" + uuid.uuid4().hex)
        directory.mkdir()
        try:
            path = directory / ("input" + suffix)
            path.write_bytes(document)
            yield path
        finally:
            shutil.rmtree(directory)

    def create(self, document: bytes, filename: str, profile: dict, kind: str) -> dict:
        if Path(filename).suffix.lower() != ".docx":
            raise ValueError("原稿范围预览目前仅支持 DOCX")
        with write_lock(self.root, self._lock):
            active = self._cleanup()
            total = sum((directory / "input.docx").stat().st_size for directory in active)
            if len(active) >= self.max_previews or total + len(document) > self.max_total_bytes:
                raise ValueError("待确认原稿较多，请关闭不再使用的预览后重试")
            with self.temporary_document(document, filename) as path:
                package = read_docx(path)
                content = read_docx_content(package["document"], package.get("styles"), numbering=package.get("numbering"),
                                            styles_reason=package.get("styles_reason", ""))
                warnings = list(content.warnings)
            identity = uuid.uuid4().hex
            directory = self._directory(identity)
            directory.mkdir()
            try:
                expires = time.time() + self.ttl_seconds
                original_name = Path(filename.replace("\\", "/")).name
                metadata = {"id": identity, "input_sha256": hashlib.sha256(document).hexdigest(),
                    "profile_sha256": profile_digest(profile), "profile_id": profile["id"], "kind": kind, "input_format": "docx",
                    "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(), "expires_timestamp": expires,
                    "filename": original_name if len(original_name) <= 255 else Path(original_name).stem[:250] + ".docx",
                    "requirements": scope_requirements(profile, kind), "warnings": warnings}
                atomic_write(directory / "input.docx", document)
                write_json(directory / "preview.json", metadata)
            except Exception:
                shutil.rmtree(directory)
                raise
            return {key: value for key, value in metadata.items() if key not in {"filename", "expires_timestamp"}}

    def catalog(self, identity: str, category: str, *, query="", offset=0, limit=10) -> dict:
        with write_lock(self.root, self._lock):
            metadata = self._metadata(identity)
            package = read_docx(self._directory(identity) / "input.docx")
            value = paragraph_style_catalog(package, query, offset, limit) if category == "styles" else section_catalog(package, offset, limit)
            return {**value, "input_sha256": metadata["input_sha256"]}

    def discard(self, identity: str) -> dict:
        with write_lock(self.root, self._lock):
            directory = self._directory(identity)
            if directory.exists():
                shutil.rmtree(directory)
            return {"discarded": True}

    @contextmanager
    def consume(self, identity: str, profile: dict, kind: str):
        with write_lock(self.root, self._lock):
            metadata = self._metadata(identity)
            if metadata["profile_sha256"] != profile_digest(profile) or metadata["kind"] != kind:
                raise ValueError("方案或材料类型已变化，请重新预览原稿")
            yield metadata, (self._directory(identity) / "input.docx").read_bytes()
