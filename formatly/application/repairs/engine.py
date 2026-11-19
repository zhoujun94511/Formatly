"""Apply validated DOCX repair plans and create immutable repair artifacts."""
from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path
from xml.etree.ElementTree import fromstring
from zipfile import ZipFile

from ...files import MAX_FILE_BYTES, W, read_docx, sha256
from ...documents.docx_semantics import active_sections
from .planning import MAX_REPAIR_CANDIDATES, _action, _observed, _plan_digest, _resolve, _safe_owner
from .mutation import _Mutation, _edits, _put, _spans
from .safety import _part_safety, _validate_page_geometry
def apply_repair_plan(input_path: Path, plan: dict, selected_ids: list[str]) -> tuple[bytes, dict]:
    """Apply a freshly rebuilt server plan, returning a new document and log."""
    input_path = Path(input_path)
    if (not isinstance(selected_ids, list) or not selected_ids or len(selected_ids) > MAX_REPAIR_CANDIDATES
            or any(not isinstance(value, str) or not value for value in selected_ids) or len(set(selected_ids)) != len(selected_ids)):
        raise ValueError("请选择不重复的有效修复项目")
    if not isinstance(plan, dict) or type(plan.get("version")) is not int or plan.get("version") != 1 or plan.get("available") is not True:
        raise ValueError("修复预览不可用，请重新预览")
    try:
        if _plan_digest(plan) != plan.get("plan_id"):
            raise ValueError("修复预览已失效，请重新预览")
        candidates = plan["candidates"]
        if not isinstance(candidates, list) or not 0 < len(candidates) <= MAX_REPAIR_CANDIDATES:
            raise ValueError("修复预览项目数量无效")
        indexed = {candidate["id"]: candidate for candidate in candidates}
        if len(indexed) != len(candidates) or any(value not in indexed for value in selected_ids):
            raise ValueError("修复项目不存在，请重新预览")
        chosen = [indexed[value] for value in selected_ids]
    except (KeyError, TypeError) as exc:
        raise ValueError("修复预览结构无效，请重新预览") from exc
    if sha256(input_path) != plan["input_sha256"]:
        raise ValueError("检测文件快照已变化，不能修复")
    package = read_docx(input_path)
    raw, reason = _part_safety(input_path, package)
    if reason:
        raise ValueError(reason)
    spans = _spans(raw)
    parents = {child: parent for parent in package["document"].iter() for child in parent}
    mutations: dict[tuple[int, ...], _Mutation] = {}
    sections = {node: index for index, node in enumerate(active_sections(package["document"]))}
    edited_sections = set()
    for candidate in chosen:
        owner = _resolve(package["document"], candidate.get("locator"), plan["input_sha256"])
        _safe_owner(owner, parents)
        if candidate.get("actual") is None or _observed(package, owner, candidate, parents, check_size_safety=True) != candidate.get("actual"):
            raise ValueError("定位处的原格式与预览不一致，请重新预览")
        chain, attributes = _action(candidate)
        if owner.tag == W + "sectPr":
            if owner not in sections:
                raise ValueError("定位处不是活动正文分节，不能自动修复")
            edited_sections.add(sections[owner])
        path = tuple(candidate["locator"]["path"])
        span = spans.get(path)
        if span is None or span.tag != owner.tag:
            raise ValueError("XML 精确定位不一致，请重新检测")
        mutation = mutations.setdefault(path, _Mutation(owner.tag.removeprefix(W), span))
        _put(mutation, chain, attributes)
    patches = []
    for mutation in mutations.values():
        patches.extend(_edits(raw, mutation))
    # A paragraph may own a spacing edit while its runs own font/size edits.
    # Their property spans do not overlap; reject any unexpected overlap.
    previous_end = -1
    for start, end, _ in sorted(patches):
        if start < previous_end:
            raise ValueError("所选格式修改范围重叠，请分批修复")
        previous_end = end
    output_xml = raw
    for start, end, replacement in sorted(patches, reverse=True):
        output_xml = output_xml[:start] + replacement + output_xml[end:]
    output_document = fromstring(output_xml)
    page_settings = None
    if edited_sections and "word/settings.xml" in package["parts"]:
        with ZipFile(input_path) as package_archive:
            page_settings = fromstring(package_archive.read("word/settings.xml"))
        if page_settings.tag != W + "settings":
            raise ValueError("文档页面设置命名空间无法确定，需在 Word/WPS 中人工修改")
    for index, section in enumerate(active_sections(output_document)):
        if index in edited_sections:
            _validate_page_geometry(section, page_settings)
    output = BytesIO()
    with ZipFile(input_path) as source, ZipFile(output, "w") as destination:
        destination.comment = source.comment
        for item in source.infolist():
            destination.writestr(item, output_xml if item.filename == "word/document.xml" else source.read(item.filename))
    document_bytes = output.getvalue()
    if len(document_bytes) > MAX_FILE_BYTES:
        raise ValueError("修复副本超过 40MB 限制，请减少所选项目")
    if sha256(input_path) != plan["input_sha256"]:
        raise ValueError("修复期间源文件发生变化，未生成有效副本")
    changes = [{**{key: candidate.get(key) for key in ("id", "rule_id", "target", "plugin", "label", "location", "expected", "actual", "locator")},
                **{key: candidate[key] for key in ("requirement_id", "requirement_ids", "scope_style_ids", "scope_section_indices")
                   if candidate.get(key) is not None}} for candidate in chosen]
    return document_bytes, {"version": 1, "plan_id": plan["plan_id"], "input_sha256": plan["input_sha256"],
                            "output_sha256": hashlib.sha256(document_bytes).hexdigest(), "changes": changes}
