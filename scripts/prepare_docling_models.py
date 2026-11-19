"""Explicitly prefetch only the local layout and table comparison models."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--download', required=True, action='store_true', help='显式允许从官方配置的公开模型仓库下载')
    args = parser.parse_args()
    downloader = importlib.import_module('docling.utils.model_downloader')
    output = args.output.resolve()
    downloader.download_models(output_dir=output, progress=True, with_layout=True, with_tableformer=True,
                               with_code_formula=False, with_picture_classifier=False, with_rapidocr=False)
    records = []
    for path in sorted(output.rglob('*')):
        if not path.is_file() or '.cache' in path.relative_to(output).parts or path.name == 'formatly-model-manifest.json':
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        records.append({'path': path.relative_to(output).as_posix(), 'bytes': path.stat().st_size,
                        'sha256': digest.hexdigest()})
    (output / 'formatly-model-manifest.json').write_text(json.dumps({
        'docling': importlib.metadata.version('docling'), 'scope': 'layout and table; local Tesseract provides OCR',
        'files': records}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'prepared': True, 'files': len(records)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
