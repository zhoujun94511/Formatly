"""Read issue evidence from immutable job inputs and their recorded checks."""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

from ..files import MAX_FILE_BYTES, W, read_docx, sha256
from ..documents.reader import MAX_WORKER_BYTES
from ..documents.processes import managed_python_worker
from ..documents.runtime import pdf_working_directory


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_snapshot(job: dict, directory: Path | None = None) -> dict:
    result, request = job.get("result") or {}, job.get("request") or {}
    if (job.get("status") != "completed" or not result or result.get("status") == "incomplete"
            or result.get("input_unchanged") is not True or result.get("rules_unchanged") is False
            or result.get("pdf_unchanged") is False or result.get("execution_errors", 0)):
        raise ValueError("检测或完整性尚未确认，不能使用此结果作为定位、比较或复核依据")
    if request:
        if request.get("input_sha256") != result.get("input_sha256"):
            raise ValueError("原稿与报告快照不一致，请重新检测")
        if request.get("pdf"):
            paired_digest = request.get("pdf_sha256")
            if (not isinstance(paired_digest, str) or len(paired_digest) != 64
                    or paired_digest != result.get("pdf_sha256")):
                raise ValueError("配对 PDF 与报告快照不一致，请重新检测")
        profile = request.get("profile")
        if profile != result.get("profile_snapshot") or hashlib.sha256(canonical(profile).encode()).hexdigest() != result.get("profile_sha256"):
            raise ValueError("规则与报告快照不一致，请重新检测")
    if not result.get("input_sha256") or not result.get("profile_sha256"):
        raise ValueError("历史报告缺少快照标识，请重新检测")
    rendering = result.get("rendered_document")
    if rendering is not None and (
            not isinstance(rendering, dict) or not request.get("render_word") or request.get("pdf")
            or rendering.get("path") != "rendered/document.pdf"
            or rendering.get("input_sha256") != result["input_sha256"]
            or not isinstance(rendering.get("pdf_sha256"), str)
            or rendering.get("pdf_sha256") != result.get("pdf_sha256")):
        raise ValueError("渲染 PDF 与检测快照不一致，请重新检测")
    if directory is not None:
        suffix = request.get("input_format") or result.get("input_format", "docx")
        if suffix not in {"docx", "pdf", "txt", "md", "json"}:
            raise ValueError("不支持的原稿格式")
        path = directory / ("input." + suffix)
        if not path.is_file() or sha256(path) != result["input_sha256"]:
            raise ValueError("原稿快照已变化，请重新检测")
        if request.get("pdf"):
            paired_pdf = directory / "input.pdf"
            if not paired_pdf.is_file() or sha256(paired_pdf) != request["pdf_sha256"]:
                raise ValueError("配对 PDF 快照已变化，请重新检测")
        if rendering is not None:
            rendered_pdf = directory / "rendered" / "document.pdf"
            if not rendered_pdf.is_file() or sha256(rendered_pdf) != rendering["pdf_sha256"]:
                raise ValueError("渲染 PDF 快照已变化，请重新检测")
    return result


def issue_key(result: dict, index: int) -> str:
    issues = result.get("issues", [])
    if type(index) is not int or not 0 <= index < len(issues):
        raise ValueError("问题位置无效，请重新读取报告")
    return hashlib.sha256(canonical([result.get("input_sha256"), result.get("profile_sha256"), index, issues[index]]).encode()).hexdigest()


def completed_engines(result: dict) -> list[dict]:
    engines = result.get("engines", [])
    if isinstance(engines, dict):
        engines = list(engines.values())
    return [engine for engine in engines if isinstance(engine, dict) and engine.get("status") == "completed"]


def observed_checks(result: dict) -> list[dict]:
    return [check for engine in completed_engines(result)
            for check in engine.get("checks", []) if isinstance(check, dict)]


def resolve_node(document, locator: dict, expected_hash: str):
    path = locator.get("path")
    if (locator.get("part") != "word/document.xml" or locator.get("input_sha256") != expected_hash
            or not isinstance(path, list) or len(path) > 100
            or any(type(item) is not int or item < 0 for item in path)):
        return None
    node = document
    try:
        for step in path:
            node = node[step]
    except IndexError:
        return None
    from xml.etree.ElementTree import tostring
    if node.tag != locator.get("tag") or hashlib.sha256(tostring(node, encoding="utf-8")).hexdigest() != locator.get("node_sha256"):
        return None
    return node


def _render_pdf(path: Path, page: int, parent: Path, expected_digest: str | None = None) -> dict:
    with pdf_working_directory(parent) as directory:
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
            raise ValueError("原稿不可读")
        data = path.read_bytes()
        if not 0 < len(data) <= MAX_FILE_BYTES or (expected_digest and hashlib.sha256(data).hexdigest() != expected_digest):
            raise ValueError("原稿快照已变化，请重新检测")
        snapshot = directory / "input.pdf"
        snapshot.write_bytes(data)
        output = directory / "preview.json"
        command = [sys.executable, "-B", "-m", "formatly.documents.preview_worker", str(snapshot), str(page), str(output)]
        with managed_python_worker(command, cwd=Path(__file__).resolve().parents[2]) as process:
            process.wait(timeout=25)
        if process.returncode or not output.is_file() or output.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("此页预览不可用，请下载原稿核对")
        preview = json.loads(output.read_text(encoding="utf-8"))
        # Only the worker's bounded PNG data is exposed, never its file path.
        png = base64.b64decode(preview["image"], validate=True)
        if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 3 * 1024 * 1024:
            raise ValueError("页面预览无效")
        return {"image_url": "data:image/png;base64," + preview["image"],
                "width_pt": preview["width_pt"], "height_pt": preview["height_pt"]}


def ocr_evidence(directory: Path, job: dict, location: str) -> dict:
    """Locate a recorded OCR observation on its unchanged source page."""
    result = validate_snapshot(job, directory)
    if result.get("input_format") != "pdf" or not isinstance(location, str) or not 0 < len(location) <= 200:
        raise ValueError("请选择报告中的 PDF 识别位置")
    extraction = directory / "document-extraction.json"
    digest = next((engine.get("evidence", {}).get("extraction_sha256") for engine in completed_engines(result)
                   if engine.get("id") == "docx-package"), None)
    if not (extraction.is_file() and extraction.stat().st_size <= MAX_WORKER_BYTES and digest):
        raise ValueError("提取快照校验失败，请重新检测")
    raw = extraction.read_bytes()
    if len(raw) > MAX_WORKER_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("提取快照校验失败，请重新检测")
    data = json.loads(raw)
    matches = [(page, review) for page in data.get("pages", []) for review in page.get("ocr_reviews", [])
               if isinstance(review, dict) and review.get("location") == location]
    if len(matches) != 1:
        raise ValueError("识别位置不存在或不唯一，请重新读取报告")
    page, review = matches[0]
    number = page.get("number")
    if type(number) is not int or not 1 <= number <= 300:
        raise ValueError("识别页码无效")
    from ..plugins.portable import ocr_review_summary
    summary = ocr_review_summary([{"number": number, "ocr_reviews": [review]}])
    observations = summary.get("observations") if summary is not None else None
    if not isinstance(observations, list) or len(observations) != 1:
        raise ValueError("识别位置没有有效的复核内容，请重新读取报告")
    observation = observations[0]
    observation_key = hashlib.sha256(canonical([result["input_sha256"], result["profile_sha256"],
                                               digest, location, observation]).encode()).hexdigest()
    response: dict = {"job_id": job["id"], "input_sha256": result["input_sha256"],
                "profile_sha256": result["profile_sha256"], "extraction_sha256": digest,
                "location": location, "observation": observation, "observation_key": observation_key,
                "preview": None, "limitations": []}
    try:
        preview = _render_pdf(directory / "input.pdf", number, directory, result["input_sha256"])
        expected = [page.get("width_mm", 0) * 72 / 25.4, page.get("height_mm", 0) * 72 / 25.4]
        if any(not math.isfinite(size) or abs(preview[key] - size) > .1
               for key, size in zip(("width_pt", "height_pt"), expected)):
            raise ValueError("页面坐标与渲染尺寸不一致")
        box = review.get("bbox")
        valid_box = (isinstance(box, list) and len(box) == 4
                     and all(type(n) in (int, float) and math.isfinite(n) for n in box)
                     and 0 <= box[0] < box[2] <= preview["width_pt"]
                     and 0 <= box[1] < box[3] <= preview["height_pt"])
        response["preview"] = {**preview, "page": number, "boxes": [box] if valid_box else []}
        if not valid_box:
            response["limitations"].append("此行没有有效坐标，请在原页中核对，未显示位置标记。")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        response["limitations"].append("页面预览不可用，请下载原稿按真实页码核对。")
    validate_snapshot(job, directory)
    if not extraction.is_file() or sha256(extraction) != digest:
        raise ValueError("提取快照已变化，请重新检测")
    return response


def issue_evidence(directory: Path, job: dict, index: int) -> dict:
    result = validate_snapshot(job, directory)
    identity = issue_key(result, index)
    issue = result["issues"][index]
    ids = set(issue.get("check_ids", []))
    checks = [item for item in observed_checks(result) if item.get("check_id") in ids]
    response: dict = {"job_id": job["id"], "issue_index": index, "issue_key": identity,
                "input_sha256": result["input_sha256"], "profile_sha256": result["profile_sha256"],
                "location": issue.get("location", "文件"), "snippets": [], "sources": [],
                "limitations": [], "preview": None}
    source = issue.get("school_sources") or issue.get("source")
    response["sources"] = source if isinstance(source, list) else [source] if source else []
    file_format = result.get("input_format", "docx")
    verified_extraction = None
    if file_format == "docx":
        package = read_docx(directory / "input.docx")
        xml_document = package["document"]
        parents = {child: parent for parent in xml_document.iter() for child in parent}
        from ..documents.docx_semantics import read_docx_content
        content = read_docx_content(xml_document, package["styles"], numbering=package.get("numbering"),
                                    styles_reason=package.get("styles_reason", ""))
        visible_paragraphs = {paragraph.element: paragraph for paragraph in content.paragraphs}
        for check in checks:
            node = resolve_node(xml_document, check.get("locator") or {}, result["input_sha256"])
            if node is None:
                continue
            paragraph = node
            while paragraph is not None and paragraph.tag != W + "p":
                paragraph = parents.get(paragraph)
            if paragraph is not None:
                # Quotes follow the same visible-text semantics as detection.
                visible = visible_paragraphs.get(paragraph)
                if visible is not None:
                    response["snippets"].append({"location": "XML段" + str(visible.index), "text": visible.text[:4000], "method": "text"})
            elif node.tag == W + "tr":
                for element in node.iter(W + "p"):
                    visible = visible_paragraphs.get(element)
                    if visible is not None and visible.text:
                        response["snippets"].append({"location": "XML段" + str(visible.index), "text": visible.text[:4000], "method": "text"})
            elif node.tag == W + "sectPr":
                response["limitations"].append("此项定位到 DOCX 分节设置；实际页码需在 Word/WPS 中核对。")
        response["limitations"].append("已提供本机应用导出的 PDF；此处仍按真实段落定位，页码对应需核对渲染文件。" if result.get("rendered_document") else
                                        "DOCX 未渲染为实际页面，使用真实段落位置，不推算页码。")
    else:
        extraction = directory / "document-extraction.json"
        extraction_digest = next((engine.get("evidence", {}).get("extraction_sha256") for engine in completed_engines(result)
                                  if engine.get("id") == "docx-package"), None)
        raw = extraction.read_bytes() if extraction.is_file() and extraction.stat().st_size <= MAX_WORKER_BYTES else b""
        verified = (bool(raw) and len(raw) <= MAX_WORKER_BYTES and extraction_digest
                    and hashlib.sha256(raw).hexdigest() == extraction_digest)
        if not verified:
            response["limitations"].append("提取快照校验不可用，请重新检测后查看片段；当前仍可按问题位置核对原稿。")
        if verified:
            verified_extraction = (extraction, extraction_digest)
            extraction_data = json.loads(raw)
            location = str(issue.get("location", ""))
            for entry in extraction_data.get("entries", []):
                if entry.get("location") == location:
                    response["snippets"].append({key: entry[key] for key in ("location", "text", "method", "page", "confidence") if key in entry})
            if file_format == "json" and location == "JSON Pointer /fields":
                from ..plugins.structured_fields import structured_fields
                fields = structured_fields(extraction_data)
                actual = issue.get("actual")
                if (fields is not None and isinstance(actual, dict) and actual.get("reason") == "missing_key"
                        and actual.get("json_pointer") == "/fields" and isinstance(actual.get("field"), str)
                        and actual["field"] not in fields and actual.get("expected_pointer") == "/fields/" + actual["field"]
                        and any(check.get("target") == "field." + actual["field"] and check.get("status") == "failed"
                                and check.get("actual") == actual for check in checks)):
                    text = json.dumps(fields, ensure_ascii=False, indent=2)
                    response["snippets"].append({"location": location, "text": text[:4000], "method": "text"})
                    if len(text) > 4000:
                        response["limitations"].append("字段表片段仅显示前4000字符，完整内容见原稿。")
            page_match = re.match(r"PDF第([1-9][0-9]*)页", location) if file_format == "pdf" else None
            if page_match:
                page_number = int(page_match[1])
                page = next((p for p in extraction_data.get("pages", []) if p.get("number") == page_number), None)
                if page:
                    spans = [span for span in page.get("spans", []) if span.get("location") == location]
                    for span in spans[:20]:
                        response["snippets"].append({"text": span.get("text", "")[:4000], "location": location,
                                                     "method": span.get("method", "text")})
                    try:
                        preview = _render_pdf(directory / "input.pdf", page_number, directory, result["input_sha256"])
                        expected_size = [page.get("width_mm", 0) * 72 / 25.4, page.get("height_mm", 0) * 72 / 25.4]
                        if any(not math.isfinite(size) or abs(preview[key] - size) > .1 for key, size in zip(("width_pt", "height_pt"), expected_size)):
                            raise ValueError("页面坐标与渲染尺寸不一致")
                        response["preview"] = {**preview, "page": page_number,
                                               "boxes": [span["bbox"] for span in spans[:20] if isinstance(span.get("bbox"), list) and len(span["bbox"]) == 4
                                                         and all(isinstance(n, (int, float)) and math.isfinite(n) for n in span["bbox"])
                                                         and 0 <= span["bbox"][0] < span["bbox"][2] <= preview["width_pt"]
                                                         and 0 <= span["bbox"][1] < span["bbox"][3] <= preview["height_pt"]]}
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        response["limitations"].append("页面预览不可用，请按真实页码下载原稿核对。")
    if not response["snippets"]:
        response["limitations"].append("此项未取得可唯一定位的原稿片段，请按问题位置及原稿人工核对。")
    response["snippets"] = list({canonical(item): item for item in response["snippets"]}.values())[:20]
    response["limitations"] = list(dict.fromkeys(response["limitations"]))
    validate_snapshot(job, directory)
    if verified_extraction is not None:
        extraction, digest = verified_extraction
        if not extraction.is_file() or sha256(extraction) != digest:
            raise ValueError("提取快照已变化，请重新检测")
    return response
