"""Bounded second OCR observations; disagreements never rewrite page text."""
from __future__ import annotations

import csv
from difflib import SequenceMatcher
import io
import math
from pathlib import Path
import re
import time
from typing import Any, Callable
import unicodedata

MAX_OCR_WORDS = 20_000
MAX_REVIEW_LINES = 6
MAX_REVIEW_OBSERVATIONS = 24
MAX_REVIEW_WORDS = 32
MAX_REVIEW_TEXT = 1_000
MAX_REVIEW_PIXELS = 1_000_000
REVIEW_SECONDS = 3.0
LOW_CONFIDENCE = 80


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def parse_tsv(text: str, scale: float) -> list[dict[str, Any]]:
    """Retain actual word frames and confidence instead of hiding low tokens in a mean."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("OCR 缩放比例无效")
    groups: dict[tuple[str | None, ...], dict[str, Any]] = {}
    words = 0
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        word = (row.get("text") or "").strip()
        if not word or row.get("level") != "5":
            continue
        try:
            confidence = float(row["conf"])
            left, top, width, height = (float(row[key]) / scale for key in ("left", "top", "width", "height"))
        except (KeyError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (confidence, left, top, width, height)) or min(width, height) <= 0:
            continue
        words += 1
        if words > MAX_OCR_WORDS:
            raise ValueError("该页 OCR 词语证据达到上限，尚未完整提取")
        key = tuple(row.get(part) for part in ("block_num", "par_num", "line_num"))
        box = [left, top, left + width, top + height]
        group = groups.setdefault(key, {"words": [], "bbox": box})
        group["words"].append({"text": word, "confidence": max(0.0, min(100.0, confidence)),
                               "bbox": [round(value, 3) for value in box]})
        group["bbox"] = [min(group["bbox"][0], box[0]), min(group["bbox"][1], box[1]),
                         max(group["bbox"][2], box[2]), max(group["bbox"][3], box[3])]
    result = []
    for group in groups.values():
        value = " ".join(word["text"] for word in group["words"])
        value = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", value)
        confidences = [word["confidence"] for word in group["words"]]
        result.append({**group, "text": value, "confidence": round(sum(confidences) / len(confidences), 2),
                       "min_word_confidence": round(min(confidences), 2)})
    return result


def differences(primary: str, alternative: str) -> list[dict[str, Any]]:
    """Offsets refer to NFKC text without whitespace, with punctuation preserved."""
    first, second = compact(primary), compact(alternative)
    return [{"kind": tag, "primary": first[start:end], "alternative": second[other_start:other_end],
             "primary_range": [start, end], "alternative_range": [other_start, other_end]}
            for tag, start, end, other_start, other_end in SequenceMatcher(None, first, second, autojunk=False).get_opcodes()
            if tag != "equal"]


def review_lines(lines: list[dict[str, Any]], image_path: Path, scale: float, directory: Path,
                 run_ocr: Callable[[Path, float], str], deadline: float) -> dict[int, dict[str, Any]]:
    """Review a few uncertain lines within a strict optional time/pixel budget.

    The callback runs local Tesseract PSM 13 on a thresholded line crop. It
    receives a timeout. Neither gold text nor a rule value enters recognition.
    """
    selected = [index for index, line in enumerate(lines) if line["min_word_confidence"] < LOW_CONFIDENCE]
    selected.sort(key=lambda index: lines[index]["min_word_confidence"])
    selected = selected[:MAX_REVIEW_OBSERVATIONS]
    observations: dict[int, dict[str, Any]] = {}
    for index in selected:
        line = lines[index]
        low_words = [word for word in line["words"] if word["confidence"] < LOW_CONFIDENCE]
        observations[index] = {"status": "not_checked", "reason": "line_limit", "canonical_source": "page_ocr",
                               "primary_text": line["text"][:MAX_REVIEW_TEXT], "bbox": [round(value, 3) for value in line["bbox"]],
                               "min_word_confidence": line["min_word_confidence"],
                               "low_confidence_words": low_words[:MAX_REVIEW_WORDS],
                               "low_confidence_word_count": len(low_words)}
    if not selected:
        return observations
    limit = min(deadline - 1.0, time.monotonic() + REVIEW_SECONDS)
    if time.monotonic() + .15 >= limit:
        for observation in observations.values():
            observation["reason"] = "time_limit"
        return observations
    from PIL import Image
    try:
        original = Image.open(image_path)
    except OSError:
        for observation in observations.values():
            observation["reason"] = "recognition_unavailable"
        return observations
    with original:
        for index in selected[:MAX_REVIEW_LINES]:
            observation, line = observations[index], lines[index]
            remaining = limit - time.monotonic()
            if remaining < .15:
                observation["reason"] = "time_limit"
                continue
            if len(line["text"]) > MAX_REVIEW_TEXT:
                observation["reason"] = "text_limit"
                continue
            box = [value * scale for value in line["bbox"]]
            padding = max(10, min(30, round((box[3] - box[1]) * .3)))
            bounds = (max(0, math.floor(box[0] - padding)), max(0, math.floor(box[1] - padding)),
                      min(original.width, math.ceil(box[2] + padding)), min(original.height, math.ceil(box[3] + padding)))
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            if min(width, height) <= 0 or width * height > MAX_REVIEW_PIXELS:
                observation["reason"] = "crop_limit"
                continue
            crop_path = directory / f"review-line-{index + 1}.png"
            try:
                with original.crop(bounds) as crop:
                    with crop.convert("L") as gray:
                        with gray.point([255 if value > 180 else 0 for value in range(256)]) as binary:
                            binary.save(crop_path)
                alternatives = parse_tsv(run_ocr(crop_path, min(1.0, max(.05, limit - time.monotonic()))), 1)
                if len(alternatives) != 1 or not alternatives[0]["text"] or len(alternatives[0]["text"]) > MAX_REVIEW_TEXT:
                    observation["reason"] = "no_single_line"
                    continue
                alternative = alternatives[0]
                changed = differences(line["text"], alternative["text"])
                observation.update(status="disagreement" if changed else "consistent", reason="local_line_observation",
                                   alternative={"text": alternative["text"], "confidence": alternative["confidence"],
                                                "min_word_confidence": alternative["min_word_confidence"],
                                                "configuration": {"psm": 13, "threshold": 180},
                                                "crop_bbox": [round(value / scale, 3) for value in bounds]},
                                   differences=changed)
            except (OSError, ValueError, RuntimeError):
                observation["reason"] = "recognition_unavailable"
            finally:
                crop_path.unlink(missing_ok=True)
    return observations
