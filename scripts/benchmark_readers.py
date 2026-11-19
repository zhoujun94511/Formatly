"""Reproducible anonymous PDF evidence benchmark, separate from school accuracy."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import sys
import time
import unicodedata
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.documents import probe_ocr, probe_pdf, read_document


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _without_punctuation(value: str) -> str:
    return "".join(character for character in _normalize(value)
                   if not unicodedata.category(character).startswith("P"))


def _character_errors(expected: str, actual: str) -> int:
    """Levenshtein count for short, independently authored benchmark gold."""
    previous = list(range(len(actual) + 1))
    for row, character in enumerate(expected, 1):
        current = [row]
        for column, observed in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (character != observed)))
        previous = current
    return previous[-1]


def _font_path(configured: Path | None) -> Path:
    candidates = [configured] if configured else [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simsun.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise ValueError("扫描样本需要本地中文字体，请用 --cjk-font 指向 TTF/TTC 文件；不会下载字体")


def generate_samples(directory: Path, cjk_font: Path | None) -> list[dict]:
    """Create six known layouts; no school/student material or external download."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        page_sizes = importlib.import_module("reportlab.lib.pagesizes")
        pdfmetrics = importlib.import_module("reportlab.pdfbase.pdfmetrics")
        cidfonts = importlib.import_module("reportlab.pdfbase.cidfonts")
        canvas_module = importlib.import_module("reportlab.pdfgen.canvas")
        image_utils = importlib.import_module("reportlab.lib.utils")
    except ImportError as exc:
        raise ValueError("基准样本生成需要 reportlab 和 Pillow；它们仅为基准工具依赖") from exc
    font_path = _font_path(cjk_font)
    pdfmetrics.registerFont(cidfonts.UnicodeCIDFont("STSong-Light"))
    width, height = page_sizes.A4
    directory.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []

    def start(sample_id: str, label: str) -> tuple[Any, dict[str, Any]]:
        sample_path = directory / f"{sample_id}.pdf"
        sample_canvas = canvas_module.Canvas(str(sample_path), pagesize=page_sizes.A4, invariant=1, pageCompression=1)
        sample_canvas.setTitle(f"Formatly anonymous benchmark: {sample_id}")
        sample_data: dict[str, Any] = {"id": sample_id, "label": label, "filename": sample_path.name, "anchors": [], "pages": 1}
        samples.append(sample_data)
        return sample_canvas, sample_data

    def line(target_canvas, target_sample: dict[str, Any], anchor_id: str, content: str,
             x_pt: float, y_pt: float, size=14, page=1):
        target_canvas.setFont("STSong-Light", size)
        target_canvas.drawString(x_pt, y_pt, content)
        target_sample["anchors"].append({"id": anchor_id, "text": content, "page": page,
            "region_pt": [x_pt - 4, height - y_pt - size - 4,
                          x_pt + pdfmetrics.stringWidth(content, "STSong-Light", size) + 4, height - y_pt + 5]})

    canvas, sample = start("chinese-single", "中文单栏")
    for index, text in enumerate(("毕业论文格式要求", "纸张使用标准 A4 页面。", "正文中文字体按学校要求设置。", "提交前核对段落和页码。")):
        line(canvas, sample, str(index + 1), text, 60, 770 - index * 40)
    sample["reading_order"] = [item["id"] for item in sample["anchors"]]
    canvas.save()

    canvas, sample = start("chinese-columns", "中文双栏")
    for side, x in (("左", 50), ("右", 320)):
        for index in range(3):
            line(canvas, sample, side + str(index + 1), f"{side}栏第{index + 1}段：独立阅读顺序。", x, 760 - index * 45, 12)
    sample["reading_order"] = [item["id"] for item in sample["anchors"]]
    canvas.save()

    canvas, sample = start("chinese-table", "中文表格与相邻单元格")
    for x in (60, 240, 510):
        canvas.line(x, 640, x, 760)
    for y in (640, 700, 760):
        canvas.line(60, y, 510, y)
    for index, (key, value) in enumerate((("材料类型", "实习报告"), ("检测编号", "BENCH-2026"))):
        line(canvas, sample, f"label-{index}", key, 75, 725 - index * 60)
        line(canvas, sample, f"value-{index}", value, 255, 725 - index * 60)
    sample["table_pairs"] = ["材料类型：实习报告", "检测编号：BENCH-2026"]
    canvas.save()

    canvas, sample = start("formula-fragments", "公式可见字符与上标")
    line(canvas, sample, "heading", "公式样本：仅比较可见字符，不评判数学含义。", 60, 770, 12)
    line(canvas, sample, "formula", "E = m c", 80, 690, 20)
    line(canvas, sample, "superscript", "2", 152, 702, 10)
    sample["formula_semantics"] = "manual_review_required"
    canvas.save()

    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    scan_font = ImageFont.truetype(str(font_path), 48)
    scan_lines = [("scan-1", "扫描材料核对", 120, 180), ("scan-2", "检测编号：BENCH-2026", 120, 300),
                  ("scan-3", "材料类型：实习报告", 120, 420)]
    scan_anchors = []
    for identity, text, x, y in scan_lines:
        draw.text((x, y), text, font=scan_font, fill="black")
        box = draw.textbbox((x, y), text, font=scan_font)
        scan_anchors.append({"id": identity, "text": text, "page": 1,
            "region_pt": [box[0] * width / 1200 - 6, box[1] * height / 1600 - 6,
                          box[2] * width / 1200 + 6, box[3] * height / 1600 + 6]})
    canvas, sample = start("chinese-scan", "中文纯扫描页")
    canvas.drawImage(image_utils.ImageReader(image), 0, 0, width=width, height=height)
    sample["anchors"] = scan_anchors
    sample["requires_ocr"] = True
    canvas.save()

    canvas, sample = start("chinese-mixed", "原生文字与扫描内容混合页")
    # The image leaves space for the native header without concealing it.
    canvas.drawImage(image_utils.ImageReader(image), 0, 0, width=width, height=height)
    line(canvas, sample, "native-heading", "原生页眉：混合材料", 60, 800, 14)
    sample["anchors"].extend(scan_anchors)
    sample["requires_ocr"] = True
    canvas.save()
    for sample in samples:
        if sample["id"] != "formula-fragments":
            sample["reference_text"] = "\n".join(anchor["text"] for anchor in sample["anchors"])
    return samples


def _localized(box: object, expected: list[float]) -> bool:
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(value, (int, float)) for value in box):
        return False
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    return expected[0] - 8 <= center[0] <= expected[2] + 8 and expected[1] - 8 <= center[1] <= expected[3] + 8


def score(sample: dict, result: dict) -> dict:
    anchors = []
    full_text = _normalize(result.get("text", ""))
    for anchor in sample["anchors"]:
        expected = _normalize(anchor["text"])
        page = next((item for item in result.get("pages", []) if item.get("number") == anchor["page"]), {})
        matched = [span for span in page.get("spans", []) if expected in _normalize(span.get("text", ""))]
        anchors.append({"id": anchor["id"], "text_found": expected in full_text,
            "correct_page": expected in _normalize(page.get("text", "")),
            "bbox_found_in_expected_region": any(_localized(span.get("bbox"), anchor["region_pt"]) for span in matched),
            "observed_boxes": [span.get("bbox") for span in matched]})
    positions = {anchor["id"]: full_text.find(_normalize(anchor["text"])) for anchor in sample["anchors"]}
    order = sample.get("reading_order")
    faithful_order = (all(positions[identity] >= 0 for identity in order)
                      and [positions[identity] for identity in order] == sorted(positions[identity] for identity in order)) if order else None
    table_pairs = [{"expected": value, "found": any(_normalize(value) == _normalize(entry.get("text", ""))
        and entry.get("table_pair") for entry in result.get("entries", []))} for value in sample.get("table_pairs", [])]
    count = len(anchors)
    # Content-only hits are diagnostic. They must not replace strict anchors:
    # punctuation changes in dates, numbers or requirements can matter.
    content_text = _without_punctuation(result.get("text", ""))
    content_anchors = Counter(_without_punctuation(anchor["text"]) for anchor in sample["anchors"])
    duplicate_occurrences = sum(max(0, content_text.count(text) - expected_count)
                                for text, expected_count in content_anchors.items() if text)
    reference = _normalize(sample.get("reference_text", ""))
    character_errors = (_character_errors(reference, full_text)
                        if reference and max(len(reference), len(full_text)) <= 4096 else None)
    return {"anchors": anchors, "anchor_recall": sum(item["text_found"] for item in anchors) / count,
        "correct_page_recall": sum(item["correct_page"] for item in anchors) / count,
        "bbox_evidence_recall": sum(item["bbox_found_in_expected_region"] for item in anchors) / count,
        "reading_order_matches_gold": faithful_order, "table_pairs": table_pairs,
        "formula_semantics": sample.get("formula_semantics", "not_applicable"),
        "content_anchor_recall": sum(bool(_without_punctuation(anchor["text"]))
                                     and _without_punctuation(anchor["text"]) in content_text
                                     for anchor in sample["anchors"]) / count,
        "duplicate_anchor_occurrences": duplicate_occurrences,
        "character_errors": character_errors,
        "reference_characters": len(reference) if reference else None,
        "character_error_rate": character_errors / len(reference) if character_errors is not None else None}


def benchmark(output_dir: Path, repetitions: int, ocr: bool, cjk_font: Path | None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = generate_samples(output_dir / "samples", cjk_font)
    available, reason = probe_pdf()
    if not available:
        raise ValueError(reason)
    runs = []
    for sample in samples:
        path = output_dir / "samples" / sample["filename"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for repetition in range(1, repetitions + 1):
            started = time.perf_counter()
            run: dict[str, Any] = {"sample_id": sample["id"], "repetition": repetition, "input_sha256": digest}
            try:
                result = read_document(path, output_dir=output_dir / "worker", ocr=ocr)
                elapsed = (time.perf_counter() - started) * 1000
                _json(output_dir / f"{sample['id']}-{repetition}-extraction.json", result)
                run.update(status="completed", elapsed_ms=round(elapsed, 3), complete=result.get("complete"),
                    requires_review=result.get("requires_review"), processed_pages=result.get("processed_pages"),
                    page_methods=[page.get("method") for page in result.get("pages", [])], warnings=result.get("warnings", []),
                    metrics=score(sample, result))
            except (OSError, ValueError) as exc:
                run.update(status="error", elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=str(exc))
            run["input_unchanged"] = hashlib.sha256(path.read_bytes()).hexdigest() == digest
            runs.append(run)
    summaries = []
    for sample in samples:
        selected = [run for run in runs if run["sample_id"] == sample["id"]]
        elapsed = sorted(run["elapsed_ms"] for run in selected)
        completed = [run for run in selected if run["status"] == "completed"]
        summaries.append({"sample_id": sample["id"], "runs": len(selected), "completed": len(completed),
            "median_ms": round(statistics.median(elapsed), 3), "p95_ms": elapsed[math.ceil(.95 * len(elapsed)) - 1],
            "minimum_anchor_recall": min((run["metrics"]["anchor_recall"] for run in completed), default=None),
            "minimum_bbox_evidence_recall": min((run["metrics"]["bbox_evidence_recall"] for run in completed), default=None),
            "all_reading_orders_match": all(run["metrics"]["reading_order_matches_gold"] is not False for run in completed)
                if sample.get("reading_order") and completed else None})
    versions: dict[str, str | None] = {}
    for package in ("pdfplumber", "pypdfium2", "Pillow", "reportlab"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    result = {"schema": "formatly.reader-benchmark.v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Anonymous synthetic PDF evidence extraction; not school-rule precision/recall or formula understanding",
        "environment": {"python": platform.python_version(), "executable": sys.executable, "platform": platform.platform(),
                        "dependencies": versions, "ocr_enabled": ocr, "ocr": probe_ocr()},
        "backends": {"formatly": {"status": "executed", "entry": "read_document -> isolated formatly.documents.worker"},
            "docling": {"status": "pending", "installed": importlib.util.find_spec("docling") is not None,
                        "reason": "未执行：需要单独验证隔离适配器与本地模型，不会自动下载模型"},
            "grobid": {"status": "pending", "client_installed": importlib.util.find_spec("grobid_client") is not None,
                       "server_verified": False, "reason": "未执行：未核验本地 GROBID 服务及固定版本"}},
        "samples": samples, "summaries": summaries, "runs": runs}
    _json(output_dir / "benchmark.json", result)
    _json(output_dir / "manifest.json", {"schema": "formatly.reader-benchmark-fixtures.v1", "samples": samples})
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成匿名 PDF 并通过 Formatly 隔离读取链路测量提取、定位和耗时；不联网、不下载模型。")
    parser.add_argument("--output-dir", required=True, type=Path, help="显式指定结果目录；样本、manifest、JSON 指标及原始提取证据全部保存在此处")
    parser.add_argument("--repetitions", type=int, default=3, help="每类样本重复次数，默认 3，范围 1-20")
    parser.add_argument("--quick", action="store_true", help="每类只运行一次；仍覆盖全部六类样本")
    parser.add_argument("--ocr", choices=("auto", "off"), default="auto", help="auto 使用已安装的本地 OCR；off 验证能力缺失时的状态")
    parser.add_argument("--cjk-font", type=Path, help="扫描样本生成所需的本地中文 TTF/TTC；不复制或分发字体")
    args = parser.parse_args(argv)
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions 必须在 1-20 之间")
    try:
        result = benchmark(args.output_dir.resolve(), 1 if args.quick else args.repetitions, args.ocr == "auto", args.cjk_font)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps({"output": str(args.output_dir.resolve() / "benchmark.json"),
        "runs": len(result["runs"]), "errors": sum(run["status"] == "error" for run in result["runs"])}, ensure_ascii=True))
    return 1 if any(run["status"] == "error" or not run["input_unchanged"] for run in result["runs"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
