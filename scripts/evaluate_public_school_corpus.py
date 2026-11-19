"""Evaluate public school clauses against independently authored anonymous files.

The manifest fixes the expected values before detection. This is a reproducible
compatibility benchmark, not an expert-labelled corpus of submitted papers.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.application.service import AuditService
from formatly.plugins.registry import PluginRegistry
from scripts.score_acceptance import score_gold

MANIFEST = ROOT / "tests" / "fixtures" / "public_school_requirements.json"
SOURCE_CACHE = ROOT / ".formatly" / "acceptance" / "public-school-sources"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def with_additional_cases(manifest: dict, path: Path) -> dict:
    """Keep the fixed cohort intact while adding an independently labelled cohort."""
    raw = path.read_bytes()
    extra = json.loads(raw)
    if not isinstance(extra, dict) or extra.get("schema") != "formatly.additional-cases.v1" or not isinstance(extra.get("cases"), list):
        raise ValueError("附加样例必须声明 formatly.additional-cases.v1 和 cases 数组")
    rulesets = {item["id"]: item for item in manifest["rulesets"]}
    known_ids = {case["id"] for case in manifest["cases"]}
    for case in extra["cases"]:
        if not isinstance(case, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", str(case.get("id", ""))):
            raise ValueError("附加 case id 无效")
        identity = case["id"]
        if identity in known_ids or case.get("ruleset") not in rulesets:
            raise ValueError("附加 case id 重复或 ruleset 不存在：" + identity)
        required_ids = {rule["id"] for rule in rulesets[case["ruleset"]]["requirements"]}
        gold = case.get("gold", {})
        contracts = case.get("contracts", {})
        if (not isinstance(gold, dict) or set(gold) != required_ids
                or not set(gold.values()) <= {"pass", "fail", "manual"}
                or not isinstance(contracts, dict) or not set(contracts) <= required_ids
                or any(not isinstance(states, list) or not states or not set(states) <= {"passed", "failed", "manual", "unsupported", "not_checked"}
                       for states in contracts.values())):
            raise ValueError("附加样例的金标准或能力契约不完整：" + identity)
        if (case.get("format") != "json" or not isinstance(case.get("note"), str)
                or ("document_fields" in case and (not isinstance(case["document_fields"], dict)
                    or any(not isinstance(key, str) or not isinstance(value, str) for key, value in case["document_fields"].items())))
                or not isinstance(case.get("paragraphs", []), list)
                or any(not isinstance(value, str) for value in case.get("paragraphs", []))):
            raise ValueError("附加样例必须提供 JSON 字段与独立说明：" + identity)
        known_ids.add(identity)
    combined = deepcopy(manifest)
    combined["cases"].extend(extra["cases"])
    combined["additional_case_sources"] = [{"filename": path.name, "sha256": _hash(raw),
                                            "scope": extra.get("scope"), "locked_at": extra.get("locked_at")}]
    return combined


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_text(source: dict) -> bytes:
    """Only selected short clauses are imported; full originals stay outside Git."""
    return (source["title"] + "\n" + source["url"] + "\n" + "\n".join(
        clause["locator"] + "\n" + clause["excerpt"] for clause in source["clauses"]
    )).encode("utf-8")


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "tr", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "br", "tr", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def original_source(source: dict, source_cache: Path) -> tuple[bytes, dict]:
    path = source_cache / source["original_filename"]
    if not path.is_file():
        return source_text(source), {"original_available": False, "input_scope": "selected_short_excerpts",
                                     "note": "离线短摘录不用于全文候选提取评分"}
    data = path.read_bytes()
    if _hash(data) != source["sha256"]:
        raise ValueError("来源缓存与锁定版本不一致：" + str(path))
    parser = _PageText()
    parser.feed(data.decode("utf-8"))
    text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    return text.encode("utf-8"), {"original_available": True, "input_scope": "complete_official_page_text",
                                  "original_sha256": _hash(data), "source_path": str(path),
                                  "normalized_text_sha256": _hash(text.encode("utf-8"))}


def source_candidate_score(school: dict, ruleset: dict, source: dict, provenance: dict) -> dict:
    """Measure source compilation separately from explicitly confirmed detection.

    Same numeric values found in an abstract/header are not credited as body
    candidates. Full-source candidate precision needs complete expert annotation
    and is deliberately not inferred from the selected-clause recall here.
    """
    candidates = school["candidates"]
    clauses = {clause["id"]: clause for clause in source["clauses"]}
    records = []
    for rule in ruleset["requirements"]:
        if rule["mode"] != "automatic" or rule.get("origin") == "operational_assumption":
            continue
        clause = clauses[rule["clause_id"]]
        relevant = [candidate for candidate in candidates if candidate["target"] == rule["target"] and candidate["mode"] == "automatic"]
        def same_value(value, wanted=rule["expected"]):
            return value.casefold() == wanted.casefold() if isinstance(value, str) and isinstance(wanted, str) else value == wanted
        matching_value = [candidate for candidate in relevant if same_value(candidate["expected"])]
        terms = clause.get("evidence_terms", [])
        matched = [candidate for candidate in matching_value
                   if terms and all(term in candidate["source_excerpt"] for term in terms)]
        records.append({"requirement_id": rule["id"], "target": rule["target"], "expected": rule["expected"],
                        "locator": clause["locator"], "hit": bool(matched),
                        "matching_candidates": [{key: item[key] for key in ("id", "target", "expected", "source_locator")} for item in matched],
                        "matching_value_elsewhere_count": len(matching_value) - len(matched),
                        "candidate_values": [item["expected"] for item in relevant],
                        "candidate_conflict": len({json.dumps(item["expected"], ensure_ascii=False, sort_keys=True) for item in relevant}) > 1})
    hits = sum(record["hit"] for record in records)
    measured = provenance["original_available"]
    return {"source_id": source["id"], "kind": ruleset["kind"], **provenance,
            "source_upload_sha256": school["sources"][-1]["sha256"], "candidate_count": len(candidates),
            "automatic_candidate_count": sum(item["mode"] == "automatic" for item in candidates),
            "manual_candidate_count": sum(item["mode"] == "manual" for item in candidates),
            "scoped_gold_count": len(records), "scoped_hits": hits if measured else None,
            "scoped_recall": hits / len(records) if measured and records else None,
            "conflicts": school["conflicts"], "requirements": records,
            "outside_automatic_scope": source.get("manual_review_scope", []),
            "scope_note": "仅统计锁定条款的候选召回；不推定全文精确率、全校规覆盖或自动确认正确率。"}


def download_sources(manifest: dict, destination: Path) -> list[dict]:
    """Keep the downloaded edition pinned; changed bytes require human review."""
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for source in manifest["sources"]:
        request = Request(source.get("retrieval_url", source["url"]),
                          headers={"User-Agent": "Formatly-public-corpus/1.0"})
        with urlopen(request, timeout=45) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("学校来源超过8MiB：" + source["id"])
        observed = _hash(data)
        path = destination / source["original_filename"]
        if observed != source["sha256"]:
            raise ValueError(f"学校来源版本发生变化，请先核对原文：{source['id']} ({observed})")
        path.write_bytes(data)
        results.append({"id": source["id"], "path": str(path), "sha256": observed})
    return results


def _zip_member(archive: ZipFile, name: str, value: str) -> None:
    entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    archive.writestr(entry, value.encode("utf-8"))


def _properties(properties: dict) -> str:
    return (f'<w:rFonts w:eastAsia="{escape(properties["eastAsia"])}" '
            f'w:ascii="{escape(properties["ascii"])}" w:hAnsi="{escape(properties["ascii"])}"/>'
            f'<w:sz w:val="{round(properties["size_pt"] * 2)}"/>')


def _section(page: dict) -> str:
    twips = lambda value: round(value * 1440 / 25.4)
    margins = " ".join(f'w:{side}="{twips(value)}"' for side, value in page["margins"].items())
    return (f'<w:sectPr><w:pgSz w:w="{twips(page["width_mm"])}" w:h="{twips(page["height_mm"])}"/>'
            f'<w:pgMar {margins} w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')


def make_docx(case: dict, ruleset: dict) -> bytes:
    """Write OOXML directly, without Formatly readers, rule helpers or writers."""
    actual = deepcopy(ruleset["document"])
    for key, value in case.get("overrides", {}).items():
        current = actual
        parts = key.split(".")
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = value
    body = actual["body"]
    styles = (f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
              '<w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="BodyText">'
              '<w:name w:val="Body Text"/><w:basedOn w:val="Normal"/>'
              f'<w:pPr><w:spacing w:line="{round(body["line_spacing"] * 240)}" w:lineRule="auto"/></w:pPr>'
              f'<w:rPr>{_properties(body)}</w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
              '<w:rPr><w:sz w:val="32"/></w:rPr></w:style></w:styles>')
    paragraphs = []
    for heading in ruleset.get("headings", []):
        if heading not in case.get("missing_headings", []):
            paragraphs.append(f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{escape(heading)}</w:t></w:r></w:p>')
    texts = case_lines(case, ruleset, include_headings=False)
    for text in texts:
        run_properties = ""
        if case.get("direct_font"):
            direct = {**body, "eastAsia": case["direct_font"]}
            run_properties = "<w:rPr>" + _properties(direct) + "</w:rPr>"
        paragraphs.append('<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>'
                          f'<w:r>{run_properties}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
    if case.get("second_section"):
        paragraphs.append('<w:p><w:pPr>' + _section(actual["page"]) + '</w:pPr></w:p>')
        page = deepcopy(actual["page"])
        page["margins"]["left"] = case["second_section"]["left"]
        paragraphs.append('<w:p><w:pPr><w:pStyle w:val="BodyText"/></w:pPr>'
                          '<w:r><w:t>第二节正文 Example 2026</w:t></w:r></w:p>')
        paragraphs.append(_section(page))
    else:
        paragraphs.append(_section(actual["page"]))
    document = f'<w:document xmlns:w="{W}"><w:body>{"".join(paragraphs)}</w:body></w:document>'
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        _zip_member(archive, "[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        _zip_member(archive, "_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        _zip_member(archive, "word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        _zip_member(archive, "word/document.xml", document)
        _zip_member(archive, "word/styles.xml", styles)
    return stream.getvalue()


def case_lines(case: dict, ruleset: dict, *, include_headings: bool = True) -> list[str]:
    if "content_lines" in case:
        values = case["content_lines"]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("匿名样例 content_lines 须为文本数组")
        return list(values)
    lines = [heading for heading in ruleset.get("headings", []) if heading not in case.get("missing_headings", [])] if include_headings else []
    if ruleset["kind"] == "certificate":
        fields = {"organization": ("实习单位名称", "示例实习单位"),
                  "start_date": ("实习开始日期", "2026-01-05"), "end_date": ("实习结束日期", "2026-03-06")}
        for name, (label, value) in fields.items():
            if name not in case.get("missing_fields", []):
                lines.append(label + "：" + value)
        lines.append("本文件为匿名测试样本，未附真实印章。")
    else:
        lines.append("这是一段匿名格式测试正文 Example 2026，用于核对显式排版属性。")
    if case.get("inline_heading"):
        lines.append("本段提及参考文献但并非独立章节标题。")
    return lines


def make_pdf(case: dict, ruleset: dict) -> bytes:
    """Minimal vector-text PDF with independently fixed page geometry."""
    page = deepcopy(ruleset["document"]["page"])
    for name, value in case.get("overrides", {}).items():
        if name in {"page.width_mm", "page.height_mm"}:
            page[name.split(".")[1]] = value
    width, height = (page[name] * 72 / 25.4 for name in ("width_mm", "height_mm"))
    commands = [f"BT /F1 12 Tf 60 {height - 60:.4f} Td".encode("ascii")]
    for line in case_lines(case, ruleset):
        commands.append(("<" + line.encode("utf-16-be").hex() + "> Tj 0 -22 Td").encode("ascii"))
    commands.append(b"ET")
    stream = b"\n".join(commands)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
               b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> >>] >>",
               f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.4f} {height:.4f}] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>".encode("ascii"),
               f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"]
    data = bytearray(b"%PDF-1.4\n%Formatly-corpus\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(data)


def specimen(case: dict, ruleset: dict) -> bytes:
    extension = case["format"]
    if extension == "docx":
        return make_docx(case, ruleset)
    if extension == "pdf":
        return make_pdf(case, ruleset)
    lines = case_lines(case, ruleset)
    if extension == "json":
        value = {"schema": "formatly.document.v1", "title": "匿名格式样本", "paragraphs": case.get("paragraphs", lines)}
        if "document_fields" in case:
            value["fields"] = case["document_fields"]
        return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    if extension == "md":
        headings = set(ruleset.get("headings", []))
        lines = [("## " if line in headings else "") + line for line in lines]
    return ("\n".join(lines) + "\n").encode("utf-8")


def prepare_profiles(service: AuditService, manifest: dict, *, source_cache: Path = SOURCE_CACHE) -> tuple[dict, list]:
    sources = {source["id"]: source for source in manifest["sources"]}
    profiles = {}
    source_scores = []
    for ruleset in manifest["rulesets"]:
        source = sources[ruleset["source_id"]]
        school = service.schools.create(source["institution"] + " · 公开规范局部基准")
        text, provenance = original_source(source, source_cache)
        school = service.schools.add_source(school["id"], source["id"] + ".txt", text, ruleset["kind"], "instructions")
        source_scores.append(source_candidate_score(school, ruleset, source, provenance))
        source_id = school["sources"][-1]["id"]
        clauses = {clause["id"]: clause for clause in source["clauses"]}
        requirements = []
        for rule in ruleset["requirements"]:
            clause = clauses[rule["clause_id"]]
            requirement = {key: rule[key] for key in ("id", "target", "expected", "label", "mode")}
            requirement.update(kind=ruleset["kind"], source_id=source_id, source_locator=clause["locator"],
                               source_excerpt=clause["excerpt"], confirmed=True)
            if rule["target"].startswith("body."):
                requirement["scope_style_ids"] = ["BodyText"]
            requirements.append(requirement)
        confirmation = service.confirm_school(school["id"], requirements, expected_version=school["version"])
        profiles[ruleset["id"]] = confirmation["profiles"][0]
    return profiles, source_scores


def supplemental_sources(service: AuditService, manifest: dict) -> list[dict]:
    records = []
    for source in manifest.get("supplemental_sources", []):
        path = ROOT / source["local_path"]
        if not path.is_file():
            records.append({"id": source["id"], "available": False, "note": "未提供锁定原件，未执行"})
            continue
        data = path.read_bytes()
        if _hash(data) != source["sha256"]:
            raise ValueError("补充来源版本不一致：" + str(path))
        school = service.schools.create(source["title"] + " · 历史来源解析样本")
        school = service.schools.add_source(school["id"], path.name, data, source["kind"], "instructions")
        original = school["sources"][-1]
        records.append({"id": source["id"], "available": True, "url": source["url"],
                        "sha256": original["sha256"], "parse_status": original["parse_status"],
                        "extraction": original["extraction"], "candidate_count": len(school["candidates"]),
                        "automatic_candidate_count": sum(item["mode"] == "automatic" for item in school["candidates"]),
                        "conflicts": school["conflicts"], "note": source["note"]})
    return records


def create_confirmed_fixture_job(service: AuditService, data: bytes, filename: str, profile: dict, kind: str) -> dict:
    """Bind this fixture's previously declared scope to its actual input bytes.

    This is confirmed-rule execution, not a source-import or user-interaction
    acceptance result. Missing fixture scope is retained as unbound; no style is
    guessed from its name, formatting or desired outcome.
    """
    if not filename.endswith(".docx"):
        return service.create(data, filename, profile_id=profile["id"], kind=kind)
    preview = service.document_preview(data, filename, profile_id=profile["id"], kind=kind)
    try:
        bindings = {"schema_version": 1, "input_sha256": preview["input_sha256"],
                    "profile_sha256": preview["profile_sha256"], "kind": kind, "items": []}
        for item in preview["requirements"]:
            key = "style_ids" if item["scope_type"] == "styles" else "section_indices"
            source_key = "source_scope_style_ids" if key == "style_ids" else "source_scope_section_indices"
            choices = item.get(source_key, [])
            bindings["items"].append({"requirement_id": item["id"], "status": "bound", key: choices}
                if choices else {"requirement_id": item["id"], "status": "unbound",
                                 "reason": "独立样例未预先声明此项执行范围，保留人工核对"})
        # The application independently verifies each style is actually used,
        # each section exists, and the input/profile digests still match.
        return service.create(data, filename, profile_id=profile["id"], kind=kind,
                              preview_id=preview["id"], scope_bindings=bindings)
    finally:
        service.discard_document_preview(preview["id"])


def evaluate(output: Path, *, manifest: dict | None = None, case_ids: set[str] | None = None,
             source_cache: Path = SOURCE_CACHE, include_supplemental: bool = True,
             profile_preparer: Callable[[AuditService, dict], tuple[dict, list]] | None = None) -> dict:
    manifest = manifest or load_manifest()
    known_ids = {case["id"] for case in manifest["cases"]}
    if case_ids is not None and (not case_ids or not case_ids <= known_ids):
        raise ValueError("case id 为空或不存在：" + ", ".join(sorted(case_ids - known_ids)))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "dataset.json").exists():
        raise ValueError("输出目录已有基准结果，请选择新目录以保留证据：" + str(output))
    specimens = output / "specimens"
    specimens.mkdir(exist_ok=True)
    service = AuditService(output / "service", registry=PluginRegistry(discover=False))
    rulesets = {item["id"]: item for item in manifest["rulesets"]}
    gold: dict[str, Any] = {"schema_version": 1, "school": "公开学校条款与匿名合成原稿（局部基准）",
            "reviewers": ["依据官网原文独立编制；本会话交叉核对；非学校专家标注"],
            "locked_at": manifest["locked_at"], "cases": []}
    executions, contracts = [], []
    try:
        profiles, source_scores = (profile_preparer(service, manifest) if profile_preparer is not None
                                   else prepare_profiles(service, manifest, source_cache=source_cache))
        supplemental = supplemental_sources(service, manifest) if include_supplemental else []
        for case in manifest["cases"]:
            if case_ids is not None and case["id"] not in case_ids:
                continue
            ruleset = rulesets[case["ruleset"]]
            data = specimen(case, ruleset)
            filename = case["id"] + "." + case["format"]
            (specimens / filename).write_bytes(data)
            job = create_confirmed_fixture_job(service, data, filename, profiles[ruleset["id"]], ruleset["kind"])
            job = service.run(job["id"])
            if job["status"] != "completed":
                raise RuntimeError(f"{case['id']} 未生成报告：{job.get('error')}")
            report = service.jobs_dir / job["id"] / "report.json"
            result = json.loads(report.read_text(encoding="utf-8"))
            gold_requirements = []
            for rule in ruleset["requirements"]:
                expected = case["gold"][rule["id"]]
                gold_requirements.append({"requirement_id": rule["id"], "target": rule["target"],
                                          "status": expected, "group": case["format"], "review_note": case["note"]})
                observations = [check for check in result["coverage"]["checks"] if check.get("requirement_id") == rule["id"]]
                checks = [check for check in observations if check.get("target") == rule["target"]]
                wrong_targets = sorted({str(check.get("target")) for check in observations if check.get("target") != rule["target"]})
                statuses = sorted({check["status"] for check in checks})
                policy = case.get("contracts", {}).get(rule["id"])
                passed = bool(statuses) and not wrong_targets and (policy is None or set(statuses) <= set(policy))
                contracts.append({"case_id": case["id"], "requirement_id": rule["id"], "target": rule["target"],
                                  "scope": "requirement_observation", "allowed_statuses": policy,
                                  "actual_statuses": statuses, "unexpected_targets": wrong_targets, "passed": passed})
            extra_contracts = case.get("extra_check_contracts", {})
            if not isinstance(extra_contracts, dict):
                raise ValueError("额外检测契约须为目标到状态数组的对象")
            for target, policy in extra_contracts.items():
                if (not isinstance(target, str) or not target or len(target) > 120
                        or not isinstance(policy, list) or not policy
                        or any(not isinstance(status, str) or status not in {
                            "passed", "failed", "manual", "unsupported", "not_checked"} for status in policy)):
                    raise ValueError("额外检测契约的目标或状态无效")
                statuses = sorted({check["status"] for check in result["coverage"]["checks"] if check.get("target") == target})
                contracts.append({"case_id": case["id"], "target": target, "scope": "additional_check",
                                  "allowed_statuses": policy, "actual_statuses": statuses,
                                  "passed": bool(statuses) and set(statuses) <= set(policy)})
            gold["cases"].append({"case_id": case["id"], "kind": ruleset["kind"],
                                  "report": report.relative_to(output).as_posix(), "input_sha256": _hash(data),
                                  "requirements": gold_requirements})
            executions.append({"case_id": case["id"], "format": case["format"], "ruleset": ruleset["id"],
                               "specimen": "specimens/" + filename, "input_sha256": _hash(data), "job_id": job["id"],
                               "result_status": result["status"], "report": report.relative_to(output).as_posix()})
    finally:
        service.close()
    scores = score_gold(gold, output)
    mismatches = [entry for entry in scores["cases"] if entry["outcome"] in {"fp", "fn"}]
    binding_errors = [entry for entry in scores["cases"] if entry["target_mismatch"] or not entry["observed_statuses"]]
    detection_ok = (not mismatches and not binding_errors and not scores["invalid_evidence_count"]
                    and all(item["passed"] for item in contracts))
    source_evaluated = bool(source_scores) and all(item["original_available"] for item in source_scores)
    source_complete = source_evaluated and all(item["scoped_hits"] == item["scoped_gold_count"] for item in source_scores)
    source_conflicts = any(item["conflicts"] for item in source_scores)
    source_status = ("not_evaluated" if not source_evaluated else "incomplete" if not source_complete
                     else "candidates_complete_needs_confirmation")
    summary = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
               "manifest_sha256": _hash(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")),
               "scope": manifest["scope"], "sample_count": len(executions),
               "formats": dict(Counter(item["format"] for item in executions)),
               "metrics": scores["metrics"], "by_kind": scores["by_kind"], "by_format": scores["by_group"],
               "unresolved_gold_count": scores.get("unresolved_gold_count", sum(
                   item["status"] == "manual" for case in gold["cases"] for item in case["requirements"])),
               "uncovered_statuses": scores["uncovered_statuses"], "invalid_evidence_count": scores["invalid_evidence_count"],
               "source_extraction": source_scores, "supplemental_source_uploads": supplemental,
               "detection_contracts_passed": detection_ok, "source_extraction_status": source_status,
               "source_extraction_complete": source_complete, "source_extraction_has_conflicts": source_conflicts,
               "source_extraction_accepted": False,
               "classification_mismatches": mismatches, "capability_contracts": contracts,
               "observation_binding_failures": binding_errors,
               "contract_failures": [item for item in contracts if not item["passed"]],
               "full_school_requirements_accepted": False,
               "passed": detection_ok and source_complete and not source_conflicts}
    for name, value in (("dataset.json", {"manifest": manifest, "executions": executions}), ("gold.json", gold),
                        ("metrics.json", scores), ("summary.json", summary)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="用公开学校条款和匿名合成稿检验 Formatly")
    parser.add_argument("--output", type=Path, help="新输出目录；默认使用 .formatly/acceptance/public-school-时间")
    parser.add_argument("--download-sources", action="store_true", help="下载并核对锁定版官方原文；不关闭 TLS 校验")
    parser.add_argument("--source-cache", type=Path, default=SOURCE_CACHE, help="官网原文缓存目录")
    parser.add_argument("--cases", nargs="*", help="仅执行指定 case id")
    parser.add_argument("--additional-cases", type=Path, help="附加独立标注的结构化字段样例；不修改原有73份样本")
    args = parser.parse_args()
    manifest = load_manifest()
    if args.additional_cases:
        manifest = with_additional_cases(manifest, args.additional_cases)
    output = args.output or ROOT / ".formatly" / "acceptance" / ("public-school-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    if args.download_sources:
        download_sources(manifest, args.source_cache)
    summary = evaluate(output, manifest=manifest, case_ids=set(args.cases) if args.cases else None,
                       source_cache=args.source_cache)
    print(json.dumps({key: summary[key] for key in ("sample_count", "formats", "metrics", "uncovered_statuses",
                                                  "detection_contracts_passed", "source_extraction_status", "passed")}, ensure_ascii=False, indent=2))
    print("结果：" + str(output.resolve() / "summary.json"))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
