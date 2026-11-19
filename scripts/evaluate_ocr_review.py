"""Generate independent scanned holdouts, then score the unchanged OCR and alternatives.

Generation uses optional ReportLab/Pillow/PDFium in an acceptance environment.
Evaluation uses Formatly's installed PDF/OCR dependencies. Gold values never enter
the production extraction call. NFKC and whitespace normalization retain signs,
decimals, dates and punctuation in all character error measurements.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GOLD_LINES = ['单位名称：示例单位', '地点说明，第二项。', '金额：-12.50；比例：3.0%', '日期：2026-02-03至2026-04-05']


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def generate(directory: Path, font_dir: Path) -> None:
    if (directory / 'expected.json').exists():
        raise SystemExit('Holdout already exists; choose a new --output to preserve its independent expected values')
    from PIL import Image, ImageDraw, ImageFont
    import pypdfium2 as pdfium
    try:
        page_sizes = importlib.import_module('reportlab.lib.pagesizes')
        image_utils = importlib.import_module('reportlab.lib.utils')
        canvas_module = importlib.import_module('reportlab.pdfgen.canvas')
    except ImportError as exc:
        raise ValueError("生成扫描样本需要 ReportLab：pip install -r requirements.txt") from exc

    cases: list[dict[str, Any]] = [{'id': f'{Path(font).stem}-{size}', 'font': font, 'size': size, 'resolution': 1200}
             for font in ('simsun.ttc', 'simhei.ttf') for size in (36, 48, 60)]
    cases += [{'id': f'{Path(font).stem}-low-res', 'font': font, 'size': 24, 'resolution': 600}
              for font in ('simsun.ttc', 'simhei.ttf')]
    sheet = Image.new('RGB', (1400, 2000), '#e8edf3')
    sheet_draw = ImageDraw.Draw(sheet)
    for index, case in enumerate(cases):
        font_path = font_dir / case['font']
        if not font_path.is_file():
            raise SystemExit(f'Required holdout font is missing: {font_path}')
        pdf = directory / (case['id'] + '.pdf')
        if not pdf.exists():
            resolution = case['resolution']
            with Image.new('RGB', (resolution, resolution * 4 // 3), 'white') as image:
                draw = ImageDraw.Draw(image)
                font = ImageFont.truetype(str(font_path), case['size'])
                for row, text in enumerate(GOLD_LINES):
                    draw.text((int(resolution * .07), int(resolution * .10) + int(resolution * .12) * row),
                              text, font=font, fill='black')
                canvas = canvas_module.Canvas(str(pdf), pagesize=page_sizes.A4, invariant=1)
                canvas.drawImage(image_utils.ImageReader(image), 0, 0, width=page_sizes.A4[0], height=page_sizes.A4[1])
                canvas.save()
        with pdfium.PdfDocument(str(pdf)) as document:
            page = document[0]
            try:
                bitmap = page.render(scale=3)
                try:
                    image = bitmap.to_pil().copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        image.save(directory / (case['id'] + '.png'))
        with image.crop((40, 150, min(image.width, 1750), min(image.height, 1150))) as preview:
            preview.thumbnail((680, 440))
            x, y = index % 2 * 700, index // 2 * 500
            sheet.paste(preview, (x + 10, y + 45))
            sheet_draw.text((x + 12, y + 12), case['id'], fill='black', font=ImageFont.load_default(size=22))
        image.close()
        case.update(file=pdf.name, sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), expected_lines=GOLD_LINES)
    sheet.save(directory / 'contact-sheet.png')
    sheet.close()
    write_json(directory / 'expected.json', {'cases': cases, 'expected_characters': sum(len(line) for line in GOLD_LINES) * len(cases),
                                            'provenance': 'synthetic independent holdout; fixed before recognition'})


def distance(first: str, second: str) -> int:
    previous = list(range(len(second) + 1))
    for index, char in enumerate(first, 1):
        current = [index]
        for other, observed in enumerate(second, 1):
            current.append(min(previous[other] + 1, current[-1] + 1, previous[other - 1] + (char != observed)))
        previous = current
    return previous[-1]


def environment() -> dict[str, Any]:
    from formatly.documents.reader import probe_ocr
    from formatly.documents.runtime import hidden_process_options
    dependencies: dict[str, str | None] = {}
    for distribution in ('pdfplumber', 'pypdfium2', 'Pillow'):
        try:
            dependencies[distribution] = version(distribution)
        except PackageNotFoundError:
            dependencies[distribution] = None
    ocr = probe_ocr()
    if ocr.get('available'):
        try:
            process = subprocess.run([ocr['executable'], '--version'], capture_output=True,
                                     timeout=5, text=True, encoding='utf-8', errors='replace', **hidden_process_options())
            ocr['version'] = (process.stdout or process.stderr).splitlines()[0] if process.returncode == 0 else 'unavailable'
        except (OSError, subprocess.TimeoutExpired):
            ocr['version'] = 'unavailable'
    return {'python': sys.version, 'python_executable': sys.executable, 'platform': platform.platform(),
            'dependencies': dependencies, 'ocr': ocr}


def evaluate(directory: Path, result_dir: Path) -> None:
    from formatly.documents.ocr_review import compact
    from formatly.documents import read_document

    result_path = result_dir / 'evaluation.json'
    if result_path.exists():
        raise SystemExit('Evaluation already exists; choose a new --results directory to preserve previous evidence')
    started_at, started = datetime.now(timezone.utc).isoformat(), time.monotonic()
    current_environment = environment()
    manifest = json.loads((directory / 'expected.json').read_text(encoding='utf-8'))
    result_dir.mkdir(parents=True, exist_ok=True)
    snapshots = result_dir / 'inputs'
    snapshots.mkdir(exist_ok=True)
    results = []
    aggregate = {'characters': 0, 'canonical_errors': 0, 'hypothetical_alternative_errors': 0,
                 'lines': 0, 'observed_alternatives': 0, 'improved_lines': 0, 'regressed_lines': 0,
                 'unchanged_lines': 0, 'unaligned_cases': 0}
    for case in manifest['cases']:
        original = directory / case['file']
        before = hashlib.sha256(original.read_bytes()).hexdigest()
        if case.get('sha256') and case['sha256'] != before:
            raise SystemExit(f'Immutable holdout digest mismatch: {case["file"]}')
        snapshot = snapshots / original.name
        shutil.copyfile(original, snapshot)
        snapshot_before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if snapshot_before != before:
            raise SystemExit(f'Input snapshot digest mismatch: {case["file"]}')
        output = result_dir / (case['id'] + '-extracted')
        output.mkdir(exist_ok=True)
        case_started = time.monotonic()
        extracted = read_document(snapshot, output_dir=output, ocr=True)
        elapsed = time.monotonic() - case_started
        after = hashlib.sha256(original.read_bytes()).hexdigest()
        snapshot_after = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if after != before or snapshot_after != before:
            raise SystemExit(f'Input changed during extraction: {case["file"]}')
        write_json(output / 'document-extraction.json', extracted)
        entries = [entry for entry in extracted['entries'] if entry.get('method') == 'ocr']
        primary = [entry['text'] for entry in entries]
        hypothetical = [entry.get('ocr_review', {}).get('alternative', {}).get('text', entry['text']) for entry in entries]
        gold = compact('\n'.join(case['expected_lines']))
        primary_errors = distance(gold, compact('\n'.join(primary)))
        candidate_errors = distance(gold, compact('\n'.join(hypothetical)))
        aggregate['characters'] += len(gold)
        aggregate['canonical_errors'] += primary_errors
        aggregate['hypothetical_alternative_errors'] += candidate_errors
        aggregate['lines'] += len(primary)
        rows = []
        if len(entries) != len(case['expected_lines']):
            aggregate['unaligned_cases'] += 1
        for index, entry in enumerate(entries):
            row = {'primary': entry['text'], 'review': entry.get('ocr_review')}
            alternative = entry.get('ocr_review', {}).get('alternative')
            if alternative:
                aggregate['observed_alternatives'] += 1
                if len(entries) == len(case['expected_lines']):
                    expected = compact(case['expected_lines'][index])
                    old = distance(expected, compact(entry['text']))
                    new = distance(expected, compact(alternative['text']))
                    category = 'improved_lines' if new < old else 'regressed_lines' if new > old else 'unchanged_lines'
                    aggregate[category] += 1
                    row.update(expected=case['expected_lines'][index], primary_errors=old, alternative_errors=new)
            rows.append(row)
        results.append({'case': case['id'], 'complete': extracted['complete'], 'requires_review': extracted['requires_review'],
                        'sha256_before': before, 'sha256_after': after, 'snapshot_sha256_before': snapshot_before,
                        'snapshot_sha256_after': snapshot_after, 'elapsed_seconds': round(elapsed, 4),
                        'expected_lines': case['expected_lines'], 'primary_errors': primary_errors,
                        'hypothetical_alternative_errors': candidate_errors, 'characters': len(gold), 'rows': rows})
        print(json.dumps({key: results[-1][key] for key in ('case', 'primary_errors', 'hypothetical_alternative_errors')}, ensure_ascii=False), flush=True)
    total = max(1, aggregate['characters'])
    summary = {**aggregate, 'canonical_cer': aggregate['canonical_errors'] / total,
               'hypothetical_alternative_cer': aggregate['hypothetical_alternative_errors'] / total,
               'canonical_replacement_enabled': False}
    value = {'summary': summary, 'results': results, 'environment': current_environment,
               'started_at': started_at, 'elapsed_seconds': round(time.monotonic() - started, 4),
               'measurement': 'NFKC + whitespace normalization; punctuation, signs and digits remain significant',
               'extraction': 'read_document: immutable input snapshot, isolated production PDF worker, saved extraction JSON',
               'alternative_policy': 'Low-confidence line observations only; alternative is evidence and never canonical text'}
    with result_path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.formatly/acceptance/ocr-review-holdout')
    parser.add_argument('--font-dir', type=Path, default=Path('C:/Windows/Fonts'))
    parser.add_argument('--results', type=Path, help='New results directory; defaults to --output; never overwrites evaluation.json')
    parser.add_argument('--generate', action='store_true', help='Create eight PDFs and independent expected values')
    parser.add_argument('--evaluate', action='store_true', help='Run current PDF/OCR extraction and compare observations')
    args = parser.parse_args()
    if not (args.generate or args.evaluate):
        parser.error('Choose --generate and/or --evaluate')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.generate:
        generate(args.output, args.font_dir)
    if args.evaluate:
        evaluate(args.output, args.results or args.output)


if __name__ == '__main__':
    main()
