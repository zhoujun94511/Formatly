"""Compare isolated local PDF readers on the same immutable, annotated inputs.

Docling Parse is the native parsing component. The explicitly selected full
pipeline uses local layout/table models and Tesseract. This command neither
downloads models nor changes the production reader.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
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
from scripts.benchmark_readers import score
from formatly.documents.processes import managed_python_worker

MAX_RESULT_BYTES = 32 * 1024 * 1024
BACKENDS = ('formatly-native', 'formatly-ocr', 'docling-parse', 'pdfium-native')
AVAILABLE_BACKENDS = (*BACKENDS, 'docling-full')


def _json(path: Path, value: object):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_snapshot(directory: Path | None):
    if directory is None or not directory.is_dir():
        return None
    files = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or '.cache' in path.relative_to(directory).parts:
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        files.append({'path': path.relative_to(directory).as_posix(),
                      'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    return files


def _versions():
    result: dict[str, str | None] = {}
    for name in ('docling', 'docling-parse', 'docling-core', 'pdfplumber', 'pypdfium2', 'psutil'):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def region_fragment_evidence(sample: dict, result: dict):
    """Score fixed gold regions without requiring one font span per sentence.

    This is separate from the benchmark's strict single-span coordinate score.
    Region boundaries are annotation input; observed boxes are never invented.
    """
    def normalized(value):
        return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()

    observations = []
    for anchor in sample.get('anchors', []):
        page = next((page for page in result.get('pages', []) if page.get('number') == anchor['page']), {})
        left, top, right, bottom = anchor['region_pt']
        fragments = []
        for span in page.get('spans', []):
            box = span.get('bbox')
            if not isinstance(box, list) or len(box) != 4:
                continue
            x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            if left - 8 <= x <= right + 8 and top - 8 <= y <= bottom + 8:
                fragments.append(span)
        fragments.sort(key=lambda fragment: fragment['bbox'][0])
        expected = normalized(anchor['text'])
        observations.append({'id': anchor['id'], 'page': anchor['page'],
            'matched': expected in normalized(page.get('text', '')) and
                       expected in normalized(''.join(fragment.get('text', '') for fragment in fragments)),
            'observed_boxes': [fragment['bbox'] for fragment in fragments]})
    return {'region_fragment_evidence_recall': (sum(item['matched'] for item in observations) / len(observations)
                                                if observations else None),
            'region_fragment_evidence': observations}


def _native_result(pages: list[dict], backend: str):
    entries = [{'text': span['text'], 'location': span['location'], 'page': page['number'],
                'method': 'text'} for page in pages for span in page['spans']]
    return {'format': 'pdf', 'text': '\n'.join(page['text'] for page in pages),
            'pages': pages, 'entries': entries, 'page_count': len(pages), 'processed_pages': len(pages),
            'complete': True, 'requires_review': True,
            'warnings': [backend + '仅比较原生文字与几何；不执行OCR、学校规则或模型语义分析']}


def extract_pdfium(path: Path):
    import pypdfium2 as pdfium
    pages = []
    with pdfium.PdfDocument(str(path)) as document:
        if not 0 < len(document) <= 250:
            raise ValueError('PDF页数超出1至250页范围')
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                width, height = page.get_size()
                spans: list[dict[str, Any]] = []
                current: dict[str, Any] | None = None
                for offset in range(textpage.count_chars()):
                    text = textpage.get_text_range(offset, 1)
                    if text in {'\r', '\n'}:
                        current = None
                        continue
                    if not text or not text.strip():
                        if current:
                            current['text'] += text
                        continue
                    left, bottom, right, top = textpage.get_charbox(offset)
                    box = [left, height - top, right, height - bottom]
                    if current and abs(current['bbox'][1] - box[1]) <= 4 and -1 <= left - current['bbox'][2] <= 18:
                        current['text'] += text
                        current['bbox'] = [min(current['bbox'][0], box[0]), min(current['bbox'][1], box[1]),
                                           max(current['bbox'][2], box[2]), max(current['bbox'][3], box[3])]
                    else:
                        current = {'text': text, 'bbox': box, 'location': f'PDF第{index + 1}页', 'method': 'text'}
                        spans.append(current)
                pages.append({'number': index + 1, 'width_pt': width, 'height_pt': height,
                              'text': textpage.get_text_bounded(), 'spans': spans, 'method': 'text'})
            finally:
                textpage.close(); page.close()
    return _native_result(pages, 'PDFium')


def extract_docling_parse(path: Path):
    try:
        parser_module = importlib.import_module('docling_parse.pdf_parser')
    except ImportError as exc:
        raise ValueError('Docling Parse比较需要在可选环境安装docling-parse；不会自动下载依赖或模型') from exc
    parser = parser_module.DoclingPdfParser(loglevel='fatal')
    levels = parser_module.ContentLevel
    document = parser.load(path_or_stream=str(path), decode_config=parser_module.DecodeConfig(),
        content_config=parser_module.ContentConfig(char_cells_content_level=levels.SKIP,
            word_cells_content_level=levels.SKIP,
            line_cells_content_level=levels.COMPUTE_AND_MATERIALIZE,
            shapes_content_level=levels.SKIP, bitmaps_content_level=levels.SKIP))
    pages = []
    try:
        if not 0 < document.number_of_pages() <= 250:
            raise ValueError('PDF页数超出1至250页范围')
        for number, page in document.iterate_pages():
            width, height = page.dimension.width, page.dimension.height
            spans = []
            for cell in page.textline_cells:
                box = cell.rect.to_bounding_box().to_top_left_origin(page_height=height)
                spans.append({'text': cell.text, 'bbox': [box.l, box.t, box.r, box.b],
                              'location': f'PDF第{number}页', 'method': 'text'})
            pages.append({'number': number, 'width_pt': width, 'height_pt': height,
                          'text': '\n'.join(span['text'] for span in spans), 'spans': spans, 'method': 'text'})
    finally:
        document.unload()
    return _native_result(pages, 'Docling Parse')


def worker(backend: str, path: Path, output: Path, artifacts: Path | None = None,
           tesseract: Path | None = None, languages=('chi_sim', 'eng')):
    if not path.is_file() or not 0 < path.stat().st_size <= 40 * 1024 * 1024 or not path.read_bytes().startswith(b'%PDF-'):
        raise ValueError('输入须为非空PDF且不超过40MiB')
    if backend.startswith('formatly-'):
        from formatly.documents import read_document
        result = read_document(path, output_dir=output.parent / 'worker-data', ocr=backend == 'formatly-ocr')
    elif backend == 'pdfium-native':
        result = extract_pdfium(path)
    elif backend == 'docling-parse':
        result = extract_docling_parse(path)
    else:
        from scripts.docling_full_reader import extract
        if artifacts is None or tesseract is None:
            raise ValueError('完整Docling比较须显式指定--docling-artifacts与--tesseract')
        result = extract(path, artifacts, tesseract, list(languages))
    _json(output, {'result': result, 'environment': {'python': platform.python_version(),
                                                   'dependencies': _versions()}})


def run_isolated(python: Path, backend: str, path: Path, output: Path, timeout: float,
                 artifacts: Path | None = None, tesseract: Path | None = None,
                 languages=('chi_sim', 'eng')) -> dict[str, Any]:
    started = time.perf_counter()
    environment = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
                       HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    arguments = [str(python), '-B', str(Path(__file__).resolve()), '--worker', backend,
                 '--input', str(path), '--result', str(output)]
    if artifacts is not None:
        arguments.extend(['--docling-artifacts', str(artifacts)])
    if tesseract is not None:
        arguments.extend(['--tesseract', str(tesseract), '--ocr-languages', ','.join(languages)])
    try:
        process_metrics = importlib.import_module('psutil')
    except ImportError:
        process_metrics = None
    monitor_errors: tuple[type[Exception], ...] = ()
    peak, measured, timed_out = 0, False, False
    with output.with_suffix('.stdout.log').open('wb') as stdout, output.with_suffix('.stderr.log').open('wb') as stderr, \
            managed_python_worker(arguments,
                                  cwd=ROOT, stdout=stdout, stderr=stderr, env=environment) as process:
        monitored = None
        if process_metrics is not None:
            monitor_errors = (process_metrics.Error,)
            try:
                monitored = process_metrics.Process(process.pid)
            except monitor_errors:
                pass
        while process.poll() is None:
            if monitored is not None:
                try:
                    members = [monitored, *monitored.children(recursive=True)]
                    total = 0
                    for member in members:
                        try:
                            total += member.memory_info().rss
                        except monitor_errors:
                            pass
                    peak, measured = max(peak, total), True
                except monitor_errors:
                    pass
            if time.perf_counter() - started > timeout:
                timed_out = True
                break
            time.sleep(.05)
        if not timed_out:
            process.wait(timeout=5)
    measurement: dict[str, Any] = {'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
                   'sampled_peak_tree_rss_bytes': peak if measured else None, 'memory_sample_interval_ms': 50,
                   'memory_scope': 'worker and descendants; sampled RSS, not exact OS peak' if measured else 'not measured: install optional psutil in comparison environment'}
    if timed_out:
        return {**measurement, 'status': 'timeout', 'error': '读取器超过单次执行时限'}
    if process.returncode or not output.is_file() or output.stat().st_size > MAX_RESULT_BYTES:
        error = output.with_suffix('.stderr.log').read_text(encoding='utf-8', errors='replace')[-3000:]
        return {**measurement, 'status': 'error', 'error': error or '未产生受限大小的JSON结果'}
    try:
        payload = json.loads(output.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('result'), dict):
            raise ValueError('Invalid reader result')
        return {**measurement, **payload, 'status': 'completed'}
    except (OSError, ValueError):
        return {**measurement, 'status': 'error', 'error': '读取器未返回合法JSON结果'}


def load_samples(manifest: Path, extras: Path | None) -> list[dict[str, Any]]:
    value = json.loads(manifest.read_text(encoding='utf-8'))
    samples: list[dict[str, Any]] = [{**sample, 'path': str((manifest.parent / 'samples' / sample['filename']).resolve()),
                'source_type': 'anonymous_synthetic'} for sample in value['samples']]
    if extras is not None:
        additional = json.loads(extras.read_text(encoding='utf-8'))
        for sample in additional['samples']:
            source = Path(sample['path'])
            if not source.is_absolute():
                source = extras.parent / source
            samples.append({**sample, 'path': str(source.resolve())})
    identities = [sample['id'] for sample in samples]
    if (any(not isinstance(identity, str) or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', identity) is None
            for identity in identities) or len(identities) != len(set(identities)) or not 1 <= len(samples) <= 30):
        raise ValueError('样本须有唯一id，合计1至30份')
    for sample in samples:
        path = Path(sample['path'])
        if not path.is_file() or not 0 < path.stat().st_size <= 40 * 1024 * 1024:
            raise ValueError('样本不存在、为空或超过40MiB：' + path.name)
        digest = _sha(path)
        if sample.get('sha256') and sample['sha256'] != digest:
            raise ValueError('样本哈希与清单不一致：' + sample['id'])
        sample['sha256'] = digest
        # Gold comes from the fixture specification, never from a reader's output.
        if (sample.get('source_type') == 'anonymous_synthetic' and sample.get('anchors')
                and sample.get('formula_semantics', 'not_applicable') == 'not_applicable'):
            sample.setdefault('reference_text', '\n'.join(anchor['text'] for anchor in sample['anchors']))
        if sample.get('source_type') == 'anonymous_synthetic':
            sample.setdefault('expected_pages', 1)
    return samples


def compare(manifest: Path, extras: Path | None, output: Path, python: Path,
            optional_python: Path, repetitions: int, timeout: float, backends=BACKENDS,
            artifacts: Path | None = None, tesseract: Path | None = None, languages=('chi_sim', 'eng')):
    if output.exists() and any(output.iterdir()):
        raise ValueError('结果目录须为新目录或空目录，避免混合历史证据')
    samples = load_samples(manifest, extras)
    model_inputs = artifact_snapshot(artifacts) if 'docling-full' in backends else None
    output.mkdir(parents=True, exist_ok=True)
    hashes = {str(path.relative_to(ROOT)): _sha(path) for path in (ROOT / 'formatly' / 'documents').glob('*.py')}
    runs = []
    for backend in backends:
        for sample in samples:
            for repetition in range(1, repetitions + 1):
                target = output / f'{backend}-{sample["id"]}-{repetition}.json'
                execution = run_isolated(python if backend.startswith('formatly-') else optional_python,
                    backend, Path(sample['path']), target, timeout, artifacts, tesseract, languages)
                extraction = execution.pop('result', None)
                record: dict[str, Any] = {'backend': backend, 'sample_id': sample['id'], 'repetition': repetition,
                          'input_sha256': sample['sha256'], **execution,
                          'input_unchanged': _sha(Path(sample['path'])) == sample['sha256']}
                if isinstance(extraction, dict):
                    record.update(pages=extraction.get('page_count'), complete=extraction.get('complete'),
                                  requires_review=extraction.get('requires_review'), warnings=extraction.get('warnings'),
                                  structures=extraction.get('structures'),
                                  text_characters=len(extraction.get('text', '')),
                                  expected_page_count_matches=(extraction.get('page_count') == sample['expected_pages']
                                      if sample.get('expected_pages') is not None else None))
                    record['metrics'] = ({**score(sample, extraction), **region_fragment_evidence(sample, extraction)}
                                         if sample.get('anchors') else None)
                runs.append(record)
    summaries = []
    for backend in backends:
        for sample in samples:
            selected = [run for run in runs if run['backend'] == backend and run['sample_id'] == sample['id']]
            successful = [run for run in selected if run['status'] == 'completed']
            summaries.append({'backend': backend, 'sample_id': sample['id'], 'completed': len(successful),
                              'runs': len(selected), 'median_ms': statistics.median(run['elapsed_ms'] for run in selected),
                              'minimum_anchor_recall': min((run['metrics']['anchor_recall'] for run in successful if run.get('metrics')), default=None),
                              'minimum_bbox_recall': min((run['metrics']['bbox_evidence_recall'] for run in successful if run.get('metrics')), default=None),
                              'minimum_region_fragment_evidence_recall': min((run['metrics']['region_fragment_evidence_recall'] for run in successful if run.get('metrics')), default=None),
                              'maximum_character_error_rate': max((run['metrics']['character_error_rate'] for run in successful if run.get('metrics') and run['metrics']['character_error_rate'] is not None), default=None),
                              'maximum_duplicate_anchor_occurrences': max((run['metrics']['duplicate_anchor_occurrences'] for run in successful if run.get('metrics')), default=None),
                              'all_reading_orders_match': all(run['metrics']['reading_order_matches_gold'] is not False for run in successful if run.get('metrics')) if successful and sample.get('reading_order') else None,
                              'maximum_sampled_peak_tree_rss_bytes': max((run['sampled_peak_tree_rss_bytes'] for run in selected if run['sampled_peak_tree_rss_bytes'] is not None), default=None)})
    value = {'schema': 'formatly.optional-reader-comparison.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
             'scope': 'Local PDF text/layout/OCR evidence comparison; not school accuracy or formula semantics',
             'samples': samples, 'runs': runs, 'summaries': summaries, 'implementation_hashes': hashes,
             'local_model_files': model_inputs,
             'local_models_unchanged': artifact_snapshot(artifacts) == model_inputs if 'docling-full' in backends else None,
             'docling_configuration': ({'ocr_languages': list(languages), 'remote_services': False,
                 'external_plugins': False, 'hub_offline': True,
                 'tesseract_sha256': _sha(tesseract) if tesseract is not None and tesseract.is_file() else None}
                 if 'docling-full' in backends else None),
             'implementation_unchanged': all((ROOT / path).is_file() and _sha(ROOT / path) == digest for path, digest in hashes.items()),
             'backends': {'formatly-native': 'production reader with OCR disabled', 'formatly-ocr': 'production reader with local OCR',
                          'docling-parse': 'Docling native parsing component; no layout/table/OCR models',
                          'pdfium-native': 'PDFium text layer only; no OCR/table models',
                          'docling-full': {'status': 'executed' if 'docling-full' in backends else 'not_executed',
                              'description': 'Explicit local layout/table models and Tesseract OCR; offline workers'},
                          'grobid': {'status': 'not_executed', 'reason': 'No verified local GROBID server; no remote service used'}}}
    _json(output / 'comparison.json', value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='离线比较PDF提取、坐标、顺序、结构、耗时与采样内存；完整Docling须显式选择和提供本地模型。')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--extra-manifest', type=Path, help='可选公开PDF清单：samples内包含id/path/source_url/sha256/anchors')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--formatly-python', type=Path, default=Path(sys.executable))
    parser.add_argument('--optional-python', type=Path, default=Path(sys.executable))
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=150)
    parser.add_argument('--backend', choices=AVAILABLE_BACKENDS, action='append')
    parser.add_argument('--worker', choices=AVAILABLE_BACKENDS, help=argparse.SUPPRESS)
    parser.add_argument('--docling-artifacts', type=Path, help='完整Docling本地模型目录；只读，不自动下载')
    parser.add_argument('--tesseract', type=Path, help='完整Docling使用的本地Tesseract可执行文件')
    parser.add_argument('--ocr-languages', default='chi_sim,eng')
    parser.add_argument('--input', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--result', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if args.input is None or args.result is None: parser.error('worker缺少输入或输出')
        worker(args.worker, args.input, args.result, args.docling_artifacts, args.tesseract,
               tuple(args.ocr_languages.split(',')))
        return 0
    if args.manifest is None or args.output_dir is None: parser.error('须指定--manifest和--output-dir')
    if not 1 <= args.repetitions <= 10 or not 1 <= args.timeout <= 300: parser.error('重复次数须1至10，单次时限须1至300秒')
    try:
        value = compare(args.manifest.resolve(), args.extra_manifest.resolve() if args.extra_manifest else None,
                        args.output_dir.resolve(), args.formatly_python.resolve(), args.optional_python.resolve(),
                        args.repetitions, args.timeout, tuple(dict.fromkeys(args.backend or BACKENDS)),
                        args.docling_artifacts.resolve() if args.docling_artifacts else None,
                        args.tesseract.resolve() if args.tesseract else None, tuple(args.ocr_languages.split(',')))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, str(exc) + '\n')
    failed = sum(run['status'] != 'completed' or not run['input_unchanged'] or run.get('complete') is False
                 for run in value['runs'])
    print(json.dumps({'report': str(args.output_dir.resolve() / 'comparison.json'), 'runs': len(value['runs']), 'failed': failed,
                      'implementation_unchanged': value['implementation_unchanged']}))
    return 1 if failed or not value['implementation_unchanged'] or value['local_models_unchanged'] is False else 0


if __name__ == '__main__':
    raise SystemExit(main())
