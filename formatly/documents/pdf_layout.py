"""Bounded geometry for PDF reading order and overlapping OCR observations."""
from __future__ import annotations

from collections import defaultdict
import math
import re
import time
import unicodedata
from typing import Any

MAX_LAYOUT_CHARACTERS = 50_000
MAX_LAYOUT_LINES = 2_500
MAX_LAYOUT_CANDIDATES = 4_000
LAYOUT_SECONDS = 2.0


class _LayoutBudgetExceeded(Exception):
    pass


def _box(chars: list[dict[str, Any]]) -> list[float]:
    return [min(float(char['x0']) for char in chars), min(float(char['top']) for char in chars),
            max(float(char['x1']) for char in chars), max(float(char['bottom']) for char in chars)]


def _text(chars: list[dict[str, Any]]) -> str:
    from pdfplumber.utils.text import extract_text
    return (extract_text(chars, x_tolerance=3, y_tolerance=3) or '').replace('\x00', '').strip()


def native_reading_order(page: Any, number: int, original: str,
                         deadline: float | None = None) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Preserve row order unless several rows support the same central gutter.

    A geometric split cannot distinguish every unruled table from prose. It is
    exposed as an estimate and never used as proof of semantic reading order.
    """
    limit = min(deadline, time.monotonic() + LAYOUT_SECONDS) if deadline is not None else time.monotonic() + LAYOUT_SECONDS

    def fallback():
        fallback_entries = [{'text': line_text.strip(), 'location': f'PDF第{number}页第{line_number}行',
                             'page': number, 'method': 'text'}
                            for line_number, line_text in enumerate(original.splitlines(), 1) if line_text.strip()]
        return original, fallback_entries, {'method': 'rows', 'requires_review': True, 'reason': 'layout_limit'}

    def check_budget():
        if time.monotonic() >= limit:
            raise _LayoutBudgetExceeded

    if len(page.chars) > MAX_LAYOUT_CHARACTERS or time.monotonic() >= limit:
        return fallback()
    lines = page.extract_text_lines(x_tolerance=3, y_tolerance=3, return_chars=True)
    if len(lines) > MAX_LAYOUT_LINES or time.monotonic() >= limit:
        return fallback()
    lines = [line for line in lines if line.get('chars') and line.get('text', '').strip()]
    width = float(page.width)
    minimum_gap = max(24.0, width * .04)
    candidates = []
    for line in lines:
        if time.monotonic() >= limit:
            return fallback()
        chars = sorted((char for char in line['chars'] if str(char.get('text', '')).strip()), key=lambda char: float(char['x0']))
        line['chars'] = chars
        for character_index in range(5, len(chars) - 6):
            gap_left, gap_right = float(chars[character_index]['x1']), float(chars[character_index + 1]['x0'])
            if gap_right - gap_left >= minimum_gap and gap_right >= width * .32 and gap_left <= width * .68:
                candidates.append((max(gap_left, width * .32), min(gap_right, width * .68)))
                if len(candidates) > MAX_LAYOUT_CANDIDATES:
                    return fallback()
    # A fixed histogram bounds candidate selection even for dense documents.
    centers = [width * (.32 + .36 * index / 64) for index in range(65)]
    support = [sum(left <= center <= right for left, right in candidates) for center in centers]
    selected = max(range(len(support)), key=support.__getitem__)
    center = centers[selected]
    metadata: dict[str, Any] = {'method': 'rows', 'requires_review': False}
    ordered = []
    pending = []

    def append_segment(segment):
        check_budget()
        if not segment:
            return
        paired = sum(bool(left) and bool(right) for _, left, right in segment)
        left_lines = sum(bool(left) for _, left, _ in segment)
        right_lines = sum(bool(right) for _, _, right in segment)
        top = min(float(line['top']) for line, _, _ in segment)
        bottom = max(float(line['bottom']) for line, _, _ in segment)
        ruled = any(float(edge.get('bottom', 0)) >= top and float(edge.get('top', 0)) <= bottom
                    and (float(edge.get('x0', 0)) <= center <= float(edge.get('x1', 0)))
                    and (abs(float(edge.get('x1', 0)) - float(edge.get('x0', 0))) >= width * .25
                         or abs(float(edge.get('bottom', 0)) - float(edge.get('top', 0))) >= 24)
                    for edge in page.edges[:2001])
        def retain_rows():
            ordered.extend((line['text'], line['chars']) for line, _, _ in segment)
            if ruled:
                metadata['table_rows_preserved'] = True
            elif paired and min(left_lines, right_lines) >= 2:
                metadata.update(requires_review=True, reason='ambiguous_columns_or_unruled_table')

        if support[selected] < 3 or paired < 3 or min(left_lines, right_lines) < 3 or ruled:
            retain_rows()
            return
        columns = {1: [], 2: []}
        for side in (1, 2):
            for item in segment:
                check_budget()
                if item[side]:
                    columns[side].append((_text(item[side]), item[side]))
        prose = all(any(re.search(r'[。！？；.!?;]$', text) for text, _ in columns[side]) for side in (1, 2))
        if not prose:
            retain_rows()
            return
        metadata.update(method='estimated_columns', requires_review=True, gutter_x_pt=round(center, 3))
        for side in (1, 2):
            ordered.extend(columns[side])

    try:
        for line in lines:
            check_budget()
            chars = line['chars']
            if not chars:
                continue
            left_chars = [char for char in chars if float(char['x1']) <= center]
            right_chars = [char for char in chars if float(char['x0']) >= center]
            crossing = len(left_chars) + len(right_chars) != len(chars)
            if left_chars and right_chars and min(float(char['x0']) for char in right_chars) - max(float(char['x1']) for char in left_chars) < minimum_gap:
                crossing = True
            if crossing:
                append_segment(pending); pending = []
                ordered.append((line['text'], chars))
            else:
                pending.append((line, left_chars, right_chars))
        append_segment(pending)
        check_budget()
    except _LayoutBudgetExceeded:
        return fallback()
    entries = [{'text': text.strip(), 'location': f'PDF第{number}页第{index}行', 'page': number,
                'method': 'text', 'bbox': [round(value, 3) for value in _box(chars)]}
               for index, (text, chars) in enumerate(ordered, 1) if text.strip()]
    text = '\n'.join(entry['text'] for entry in entries) if metadata['method'] == 'estimated_columns' else original
    return text, entries, metadata


def _normalized(text: str) -> str:
    compact = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))
    # OCR commonly confuses a label's colon and comma. Keep numeric
    # punctuation, signs and every letter/digit so changed values stay visible.
    return re.sub(r'(?<=\D)[:,]', ':', compact)


def merge_ocr_observations(native: list[dict[str, Any]], ocr_entries: list[dict[str, Any]],
                           ocr_spans: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Suppress only near-identical text at the same painted page position.

    Raw OCR strings and boxes remain in the duplicate evidence. Different
    positions are never collapsed merely because their text repeats.
    """
    bins = defaultdict(list)
    for item in native:
        box = item.get('bbox')
        if not isinstance(box, list) or len(box) != 4:
            continue
        bins[math.floor((box[1] + box[3]) / 40)].append(item)
    retained_entries, retained_spans, duplicates = [], [], []
    for index, entry in enumerate(ocr_entries):
        span = ocr_spans[index] if index < len(ocr_spans) else None
        box = span.get('bbox') if span else None
        match = None
        if isinstance(box, list) and len(box) == 4 and 0 < box[3] - box[1] < 640:
            normalized = _normalized(entry['text'])
            for row in range(math.floor(box[1] / 20) - 1, math.ceil(box[3] / 20) + 2):
                for item in bins.get(row, []):
                    other = item['bbox']
                    overlap_x = max(0, min(box[2], other[2]) - max(box[0], other[0]))
                    overlap_y = max(0, min(box[3], other[3]) - max(box[1], other[1]))
                    area = min((box[2] - box[0]) * (box[3] - box[1]), (other[2] - other[0]) * (other[3] - other[1]))
                    if area <= 0 or overlap_x * overlap_y / area < .65:
                        continue
                    native_text = _normalized(item['text'])
                    if not 4 <= min(len(normalized), len(native_text)) <= max(len(normalized), len(native_text)) <= 1000:
                        continue
                    if normalized == native_text:
                        match = item
                        break
                if match:
                    break
        if match is not None:
            duplicates.append({'ocr': entry, 'span': span, 'native': match, 'reason': 'overlapping_native_text'})
        else:
            retained_entries.append(entry)
            if span is not None:
                retained_spans.append(span)
    return native + retained_entries, retained_spans, duplicates
