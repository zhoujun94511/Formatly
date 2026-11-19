"""Isolated PDF parsing/rendering/OCR worker; no web, storage or rule decisions."""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from ..privacy import public_ocr_information, redact_local_paths
from .ocr_review import LOW_CONFIDENCE, MAX_REVIEW_TEXT, parse_tsv, review_lines
from .pdf_layout import merge_ocr_observations, native_reading_order
from .reader import (
    MAX_FILE_BYTES,
    MAX_OCR_PAGES,
    MAX_PDF_PAGES,
    MAX_TEXT_BYTES,
    probe_ocr,
)
from .runtime import hidden_process_options, render_pdf_bitmap

MAX_CHARACTERS = 200_000
MAX_SPANS = 40_000
WORKER_SECONDS = 110
MAX_RENDER_PIXELS = 10_000_000
MAX_TABLE_EDGES = 2_000
MAX_TABLES_PER_PAGE = 20
MAX_TABLE_CELLS_PER_PAGE = 2_000
MAX_TABLE_ROWS = 200
MAX_ENTRIES = 40_000


class _PdfExtraction(TypedDict):
    format: str
    text: str
    entries: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    warnings: list[str]
    complete: bool
    requires_review: bool
    page_count: int
    processed_pages: int
    # Process paths remain private to the worker; extraction records contain
    # only the shared public OCR capability/evidence contract.
    ocr: dict[str, Any]


def _table_entries(page, number, deadline) -> tuple[list[dict[str, Any]], list[str]]:
    """Recover explicit neighbouring form cells with bounded table geometry."""
    entries, warnings = [], []
    if not page.edges:
        return entries, warnings
    if len(page.edges) > MAX_TABLE_EDGES or time.monotonic() >= deadline:
        return [], [f"PDF第{number}页表格边线或处理时限超限，未完整解析单元格关系"]
    tables = page.find_tables()
    cell_count = 0
    for table_number, table in enumerate(tables, 1):
        cell_count += len(table.cells)
        if (table_number > MAX_TABLES_PER_PAGE or cell_count > MAX_TABLE_CELLS_PER_PAGE
                or time.monotonic() >= deadline):
            warnings.append(f"PDF第{number}页表格数量、单元格数量或处理时限超限，部分表格关系未解析")
            break
        rows = table.extract(x_tolerance=3, y_tolerance=3)
        for row_number, cells in enumerate(rows, 1):
            if row_number > MAX_TABLE_ROWS:
                warnings.append(f"PDF第{number}页表格{table_number}超过200行，后续单元格关系未解析")
                break
            cells = [re.sub(r"\s+", " ", cell).strip() if isinstance(cell, str) else "" for cell in cells]
            for index in range(len(cells) - 1):
                left, right = cells[index:index + 2]
                if not left or not right:
                    continue
                if len(left) + len(right) > 1_000:
                    warnings.append(f"PDF第{number}页表格{table_number}含超长单元格，仅保留普通文本证据")
                    continue
                entries.append({"text": left.rstrip("：:") + "：" + right, "page": number,
                                "location": f"PDF第{number}页表格{table_number}行{row_number}，单元格{index + 1}–{index + 2}",
                                "method": "text", "table_pair": True})
    return entries, list(dict.fromkeys(warnings))


def _spans(chars, page_number):
    """Retain observable font runs, without inventing Word paragraph styles."""
    output, previous = [], None
    for char in sorted(chars, key=lambda item: (round(float(item["top"]) / 3), float(item["x0"]))):
        text = str(char.get("text", ""))
        if not text.strip():
            continue
        font = str(char.get("fontname", "")) or None
        size = round(float(char.get("size", 0)), 3) or None
        box = [round(float(char[key]), 3) for key in ("x0", "top", "x1", "bottom")]
        key = (font, size)
        if (previous and previous["key"] == key and abs(previous["bbox"][1] - box[1]) <= 2
                and -1 <= box[0] - previous["bbox"][2] <= max(5.0, (size or 0.0) * .8)):
            previous["text"] += text
            previous["bbox"][2] = max(previous["bbox"][2], box[2])
            previous["bbox"][3] = max(previous["bbox"][3], box[3])
        else:
            previous = {"key": key, "text": text, "font": font, "size_pt": size, "bbox": box,
                        "location": f"PDF第{page_number}页，x={box[0]}pt，y={box[1]}pt", "method": "text",
                        "paint_visibility": "painted"}
            output.append(previous)
    for span in output:
        span.pop("key")
    return output


def _ocr_tsv(image_path: Path, probe: dict, psm: int, timeout: float) -> str:
    command = [probe["executable"], str(image_path), "stdout", "-l", "+".join(probe["selected_languages"]), "--psm", str(psm), "tsv"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                text=True, encoding="utf-8", errors="replace", **hidden_process_options())
    except subprocess.TimeoutExpired as exc:
        raise ValueError("该页本地 OCR 超时，文字尚未完整提取") from exc
    if result.returncode:
        raise ValueError("该页本地 OCR 失败，请检查 Tesseract 语言数据及原件")
    return result.stdout


def _ocr_page(pdf, index, directory, probe, deadline) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import pypdfium2 as pdfium
    remaining = deadline - time.monotonic()
    if remaining < 2:
        raise ValueError("本次 PDF OCR 已达到总处理时限")
    with pdfium.PdfDocument(str(pdf)) as document:
        page = document[index]
        try:
            width, height = page.get_size()
            pixels = width * height
            if not math.isfinite(pixels) or pixels <= 0:
                raise ValueError("PDF 页面尺寸无效")
            scale = min(3.0, math.sqrt(MAX_RENDER_PIXELS / pixels))
            if scale < .5:
                raise ValueError("PDF 页面尺寸过大，无法安全进行 OCR")
            bitmap = render_pdf_bitmap(page, scale)
            try:
                image = bitmap.to_pil()
                image_path = directory / f"page-{index + 1}.png"
                image.save(image_path)
            finally:
                bitmap.close()
        finally:
            page.close()
    try:
        lines = parse_tsv(_ocr_tsv(image_path, probe, 3, max(1.0, min(25.0, deadline - time.monotonic()))), scale)
        reviews = review_lines(lines, image_path, scale, directory,
                               lambda path, timeout: _ocr_tsv(path, probe, 13, timeout), deadline)
    finally:
        image_path.unlink(missing_ok=True)
    entries, spans = [], []
    for number, line in enumerate(lines, 1):
        location = f"PDF第{index + 1}页OCR第{number}行"
        entry = {"text": line["text"], "location": location, "page": index + 1, "method": "ocr",
                 "confidence": line["confidence"], "min_word_confidence": line["min_word_confidence"]}
        review = reviews.get(number - 1)
        if review is None and line["min_word_confidence"] < LOW_CONFIDENCE:
            review = {"status": "not_checked", "reason": "observation_limit", "canonical_source": "page_ocr",
                      "primary_text": line["text"][:MAX_REVIEW_TEXT], "bbox": [round(value, 3) for value in line["bbox"]],
                      "min_word_confidence": line["min_word_confidence"]}
        if review is not None:
            entry["ocr_review"] = review
        entries.append(entry)
        spans.append({"text": line["text"], "font": None, "size_pt": None,
                      "bbox": [round(value, 3) for value in line["bbox"]], "location": location,
                      "confidence": line["confidence"], "min_word_confidence": line["min_word_confidence"],
                      "ocr_review_status": review["status"] if review else "not_requested", "method": "ocr"})
    return entries, spans


def parse_pdf(path: Path, directory: Path, ocr: bool) -> _PdfExtraction:
    import pdfplumber

    from .pdf_visibility import EvidencePage
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("PDF 为空、不存在或超过40MB限制")
    pages: list[dict[str, Any]] = []
    ocr_probe = probe_ocr()
    result: _PdfExtraction = {
        "format": "pdf", "text": "", "entries": [], "pages": pages, "warnings": [], "complete": True,
        "requires_review": False, "page_count": 0, "processed_pages": 0, "ocr": public_ocr_information(ocr_probe),
    }
    deadline = time.monotonic() + WORKER_SECONDS
    ocr_pages = chars_total = spans_total = text_total = entry_bytes_total = 0
    try:
        with pdfplumber.open(path) as document:
            if document.doc.encryption:
                raise ValueError("不支持加密 PDF，请提供已解密的副本")
            result["page_count"] = len(document.pages)
            if not result["page_count"]:
                raise ValueError("PDF 不包含有效页面")
            for index, page in enumerate(document.pages):
                if index >= MAX_PDF_PAGES or time.monotonic() >= deadline:
                    result["complete"] = False
                    result["warnings"].append("PDF 页数或处理时限达到上限；其余页面未读取，请拆分后重新检查")
                    break
                page = EvidencePage(document, page.page_obj, page.page_number, initial_doctop=page.initial_doctop)
                width, height = float(page.width), float(page.height)
                if not all(math.isfinite(value) and 0 < value < 100_000 for value in (width, height)):
                    raise ValueError("PDF 页面尺寸无效或超限")
                raw_chars = page.chars
                chars_total += len(raw_chars)
                if chars_total > MAX_CHARACTERS:
                    result["complete"] = False
                    result["warnings"].append("PDF 字符证据超过20万字符，后续页面未完整读取，请拆分文档")
                    page.close()
                    break
                painted_page = page.filter(lambda obj: obj.get("object_type") != "char" or obj.get("paint_visibility") == "painted")
                chars = painted_page.chars
                hidden_chars = sum(char.get("paint_visibility") == "hidden" for char in raw_chars)
                unverified_chars = sum(char.get("paint_visibility") == "unverified" for char in raw_chars)
                auxiliary_text = ""
                if hidden_chars or unverified_chars:
                    auxiliary_page = page.filter(lambda obj: obj.get("object_type") == "char" and obj.get("paint_visibility") != "painted")
                    auxiliary_text = (auxiliary_page.extract_text(x_tolerance=3, y_tolerance=3) or "").replace("\x00", "")
                    result["requires_review"] = True
                    result["warnings"].append(f"PDF第{index + 1}页有{hidden_chars}个不可见文字字符、{unverified_chars}个绘制状态待核对字符；仅保留为辅助证据，不用于标题或字体通过结论")
                native = painted_page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                native = native.replace("\x00", "")
                native, entries, reading_order = native_reading_order(painted_page, index + 1, native, deadline)
                if reading_order['requires_review']:
                    result['requires_review'] = True
                    if reading_order.get('reason') == 'layout_limit':
                        result['warnings'].append(f'PDF第{index + 1}页阅读顺序分析达到资源上限，保留按行文字；语义顺序需复核')
                    elif reading_order['method'] == 'estimated_columns':
                        result['warnings'].append(f'PDF第{index + 1}页按几何位置组织双栏文字；无框表格或复杂分栏的语义顺序仍需复核')
                    else:
                        result['warnings'].append(f'PDF第{index + 1}页有疑似分栏或无框表格，暂保留按行顺序；语义顺序需复核')
                useful = len(re.findall(r"[\w\u3400-\u9fff]", re.sub(r"\(cid:\d+\)", "", native)))
                garbled = bool(re.search(r"\(cid:\d+\)|\ufffd", native))
                # A selectable page header does not make a scanned body
                # extractable. Significant images need OCR even when there
                # are many native characters elsewhere on the same page.
                # Ignore small logos in an otherwise readable text page.
                image_areas = [max(0.0, min(float(image["x1"]), width) - max(float(image["x0"]), 0.0))
                               * max(0.0, min(float(image["bottom"]), height) - max(float(image["top"]), 0.0))
                               / (width * height) for image in page.images]
                image_coverage = min(1.0, sum(image_areas))
                scan = max(image_areas, default=0.0) >= .15 or image_coverage >= .30
                # Outlined text may be vector paths without image objects, and
                # a broken ToUnicode map can affect embedded text. Rendering
                # lets OCR recover both; an empty text layer is not proof of a
                # blank page when visible drawing objects remain.
                graphical = bool(page.images or page.curves or page.rects)
                needs_ocr = scan or garbled or bool(unverified_chars) or (not useful and graphical)
                extracted = {"number": index + 1, "width_mm": round(width * 25.4 / 72, 3),
                             "height_mm": round(height * 25.4 / 72, 3), "method": "text", "text": native,
                             "spans": _spans(chars, index + 1), "image_coverage": round(image_coverage, 4),
                             "non_text_objects": len(page.images) + len(page.curves) + len(page.rects)
                                                 + len(page.lines) + len(page.annots or []),
                             "auxiliary_text": auxiliary_text, "hidden_characters": hidden_chars,
                             "unverified_characters": unverified_chars, 'reading_order': reading_order}
                if needs_ocr:
                    result["requires_review"] = True
                    if not ocr or not result["ocr"]["available"] or ocr_pages >= MAX_OCR_PAGES:
                        result["complete"] = False
                        extracted["method"] = "unavailable"
                        reason = ("OCR 未启用" if not ocr else "达到20页 OCR 上限" if ocr_pages >= MAX_OCR_PAGES else result["ocr"]["reason"])
                        result["warnings"].append(f"PDF第{index + 1}页疑似扫描页：{reason}；该页文字尚未完整核验")
                    else:
                        ocr_pages += 1
                        try:
                            ocr_entries, ocr_spans = _ocr_page(path, index, directory, ocr_probe, deadline)
                            if not ocr_entries:
                                raise ValueError("未识别到可读文字，可能是空白页、图表或识别失败")
                            confidence = round(sum(item["confidence"] * len(item["text"]) for item in ocr_entries)
                                               / max(1, sum(len(item["text"]) for item in ocr_entries)), 2)
                            if entries:
                                entries, retained_spans, duplicates = merge_ocr_observations(entries, ocr_entries, ocr_spans)
                                extracted['ocr_duplicates'] = duplicates
                                method, spans = "mixed", extracted["spans"] + retained_spans
                            else:
                                entries, method, spans = ocr_entries, "ocr", ocr_spans
                            extracted.update(method=method, text="\n".join(item["text"] for item in entries), spans=spans,
                                             confidence=confidence, native_text=native,
                                             ocr_text="\n".join(item["text"] for item in ocr_entries),
                                             ocr_reviews=[{"location": item["location"], **item["ocr_review"]}
                                                          for item in ocr_entries if "ocr_review" in item])
                            if any(item.get("min_word_confidence", item["confidence"]) < LOW_CONFIDENCE for item in ocr_entries):
                                result["warnings"].append(f"PDF第{index + 1}页含低置信度 OCR 文字或标点，请对照词语坐标及备选识别复核；备选不会改写原始文字")
                        except (OSError, ValueError, RuntimeError) as exc:
                            result["complete"] = False
                            extracted["method"] = "unavailable"
                            result["warnings"].append(f"PDF第{index + 1}页：" + redact_local_paths(
                                str(exc), path, directory, ocr_probe.get("executable")))
                elif not useful:
                    extracted["method"] = "blank"
                    result["requires_review"] = True
                    result["warnings"].append(f"PDF第{index + 1}页无可提取文字；请确认是否为空白页或图形化文本")
                elif garbled:
                    result["requires_review"] = True
                    result["complete"] = False
                    result["warnings"].append(f"PDF第{index + 1}页含未知字符映射，文字尚未完整核验")
                if extracted["method"] == "text":
                    table_entries, table_warnings = _table_entries(painted_page, index + 1, deadline)
                    entries.extend(table_entries)
                    if table_warnings:
                        result["warnings"].extend(table_warnings)
                        result["complete"] = False
                encoded_length = len(extracted["text"].encode("utf-8")) + len(auxiliary_text.encode("utf-8")) + 2
                page_entry_bytes = sum(len(entry["text"].encode("utf-8")) + 1 for entry in entries)
                spans_total += len(extracted["spans"])
                if (text_total + encoded_length > MAX_TEXT_BYTES or spans_total > MAX_SPANS
                        or entry_bytes_total + page_entry_bytes > MAX_TEXT_BYTES
                        or len(result["entries"]) + len(entries) > MAX_ENTRIES):
                    result["complete"] = False
                    result["warnings"].append("PDF 提取文本、表格或字符属性证据达到上限；部分页面未读取，请拆分文件")
                    page.close()
                    break
                text_total += encoded_length
                entry_bytes_total += page_entry_bytes
                result["entries"].extend(entries)
                pages.append(extracted)
                page.close()
            result["processed_pages"] = len(pages)
            result["text"] = "\n\n".join(extracted_page["text"] for extracted_page in pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF 损坏、加密或不可解析，请提供可正常打开的 PDF 副本") from exc
    if ocr_pages:
        result["warnings"].append("扫描页已进行本地 OCR；字体和字号无法由识别文字还原，识别结果与低置信度文字须对照原件复核")
    result["ocr"]["processed_pages"] = ocr_pages
    result["requires_review"] = result["requires_review"] or not result["complete"]
    return result


def main() -> int:
    path, output, enabled = sys.argv[1:]
    output = Path(output)
    try:
        result = parse_pdf(Path(path), output.parent, enabled == "1")
    except Exception as exc:
        output.write_text(json.dumps({"error": redact_local_paths(str(exc), path, output.parent)}, ensure_ascii=False), encoding="utf-8")
        return 2
    output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
