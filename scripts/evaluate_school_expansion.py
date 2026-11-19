"""Evaluate new official school originals separately from locked cohorts."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formatly.application.service import AuditService
from scripts.evaluate_public_school_corpus import (
    download_sources, evaluate, original_source, source_candidate_score,
)
from scripts.score_acceptance import score_gold

MANIFEST = ROOT / 'tests/fixtures/school_expansion_requirements.json'
SOURCE_CACHE = ROOT / '.formatly/acceptance/school-expansion-sources'


def source_metrics(manifest: dict, extractions: list[dict]) -> dict:
    """Count only locked automatic clauses, without inventing source precision."""
    sources = {source['id']: source for source in manifest['sources']}
    by_format, by_target = {}, {}
    for extraction in extractions:
        source_format = Path(sources[extraction['source_id']]['original_filename']).suffix.lstrip('.').lower()
        format_group = by_format.setdefault(source_format, {'hits': 0, 'total': 0})
        for requirement in extraction['requirements']:
            target_group = by_target.setdefault(requirement['target'], {'hits': 0, 'total': 0})
            for group in (format_group, target_group):
                group['total'] += 1
                group['hits'] += int(requirement['hit'])
    for groups in (by_format, by_target):
        for group in groups.values():
            group['recall'] = group['hits'] / group['total'] if group['total'] else None
    hits = sum(item['scoped_hits'] for item in extractions)
    total = sum(item['scoped_gold_count'] for item in extractions)
    return {'hits': hits, 'total': total, 'recall': hits / total if total else None,
            'by_format': by_format, 'by_target': by_target,
            'precision_measured': False, 'scope': 'Independently locked automatic clauses only'}


def read_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    sources = value['sources']
    rulesets = {ruleset['id']: ruleset for ruleset in value['rulesets']}
    source_ids = {source['id'] for source in sources}
    if not sources or len(source_ids) != len(sources) or len(rulesets) != len(value['rulesets']):
        raise ValueError('学校来源和规则集须非空且ID唯一')
    for source in sources:
        filename = source['original_filename']
        if (Path(filename).name != filename or '/' in filename or '\\' in filename
                or not re.fullmatch(r'[0-9a-f]{64}', source['sha256'])):
            raise ValueError('来源须有安全文件名和固定SHA256')
    cases = value['cases']
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('匿名样例须非空且ID唯一')
    for ruleset in rulesets.values():
        if ruleset['source_id'] not in source_ids or not ruleset['requirements']:
            raise ValueError('规则集来源不存在或要求为空')
    for case in cases:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,119}', case['id']):
            raise ValueError('匿名样例ID无效')
        ruleset = rulesets[case['ruleset']]
        required = {rule['id'] for rule in ruleset['requirements']}
        contracts = case.get('contracts')
        if (set(case['gold']) != required or not set(case['gold'].values()) <= {'pass', 'fail', 'manual'}
                or case['format'] not in {'docx', 'pdf', 'txt', 'md', 'json'}):
            raise ValueError('匿名样例的预期状态须完整、独立且使用支持格式')
        if (not isinstance(contracts, dict) or set(contracts) != required
                or any(not isinstance(states, list) or not states
                       or not set(states) <= {'passed', 'failed', 'manual', 'unsupported', 'not_checked'}
                       for states in contracts.values())):
            raise ValueError('每条要求须有独立完整的显式能力契约')
    return value


def prepare_original_profiles(service: AuditService, manifest: dict, source_cache: Path) -> tuple[dict, list]:
    profiles, scores = {}, []
    sources = {source['id']: source for source in manifest['sources']}
    for ruleset in manifest['rulesets']:
        source = sources[ruleset['source_id']]
        path = source_cache / source['original_filename']
        if not path.is_file():
            raise ValueError('未提供完整锁定原件：' + source['id'])
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != source['sha256']:
            raise ValueError('完整来源SHA256不一致：' + source['id'])
        if path.suffix.lower() in {'.html', '.htm'}:
            payload, provenance = original_source(source, source_cache)
            upload_name = source['id'] + '.txt'
            input_method = 'complete_official_html_text'
        else:
            payload, upload_name = data, path.name
            provenance = {'original_available': True, 'input_scope': 'complete_official_original',
                          'original_sha256': digest}
            input_method = 'original_file_upload'
        school = service.schools.create(source['institution'] + ' · 独立学校条款验证')
        school = service.schools.add_source(school['id'], upload_name, payload, ruleset['kind'],
                                           source.get('role', 'instructions'))
        # Whitespace normalization accounts for PDF line and page breaks. It
        # cannot add a value, source context, or a candidate not actually read.
        scored_school = deepcopy(school)
        for candidate in scored_school['candidates']:
            candidate['source_excerpt'] = re.sub(r'\s+', '', candidate['source_excerpt'])
        scored_source = deepcopy(source)
        for clause in scored_source['clauses']:
            clause['evidence_terms'] = [re.sub(r'\s+', '', term) for term in clause.get('evidence_terms', [])]
        score = source_candidate_score(scored_school, ruleset, scored_source, provenance)
        uploaded = school['sources'][-1]
        score.update(input_method=input_method, uploaded_filename=upload_name,
                     ruleset_id=ruleset['id'], original_bytes=len(data), upload_bytes=len(payload),
                     source_parse_status=uploaded.get('parse_status'), extraction=uploaded.get('extraction'),
                     normalized_text_sha256=uploaded.get('text_sha256'),
                     full_school_requirements_accepted=False)
        scores.append(score)
        clauses = {clause['id']: clause for clause in source['clauses']}
        confirmed = []
        for rule in ruleset['requirements']:
            clause = clauses[rule['clause_id']]
            requirement = {key: rule[key] for key in ('id', 'target', 'expected', 'label', 'mode')}
            requirement.update(kind=ruleset['kind'], source_id=uploaded['id'],
                               source_locator=clause['locator'], source_excerpt=clause['excerpt'], confirmed=True)
            if rule['target'].startswith('body.'):
                requirement['scope_style_ids'] = ['BodyText']
            confirmed.append(requirement)
        result = service.confirm_school(school['id'], confirmed, expected_version=school['version'])
        profiles[ruleset['id']] = result['profiles'][0]
    return profiles, scores


def run(output: Path, manifest_path: Path = MANIFEST, source_cache: Path = SOURCE_CACHE, *,
        fetch: bool = False) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    if output.exists() and any(output.iterdir()):
        raise ValueError('请使用新的学校扩展验证目录，保留已有基准结果')
    if fetch:
        download_sources(manifest, source_cache)
    started = time.perf_counter()
    summary = evaluate(output, manifest=manifest, source_cache=source_cache, include_supplemental=False,
                       profile_preparer=lambda service, document: prepare_original_profiles(service, document, source_cache))
    scores = json.loads((output / 'metrics.json').read_text(encoding='utf-8'))
    gold = json.loads((output / 'gold.json').read_text(encoding='utf-8'))
    case_rulesets = {case['id']: case['ruleset'] for case in manifest['cases']}
    by_ruleset = {}
    for ruleset in manifest['rulesets']:
        subset = {**gold, 'cases': [case for case in gold['cases'] if case_rulesets[case['case_id']] == ruleset['id']]}
        by_ruleset[ruleset['id']] = score_gold(subset, output)['metrics']
    by_source = {}
    for source in manifest['sources']:
        selected = {ruleset['id'] for ruleset in manifest['rulesets'] if ruleset['source_id'] == source['id']}
        subset = {**gold, 'cases': [case for case in gold['cases'] if case_rulesets[case['case_id']] in selected]}
        by_source[source['id']] = score_gold(subset, output)['metrics']
    full_read = all(item.get('extraction', {}).get('complete') is True
                    and item.get('extraction', {}).get('processed_pages') == item.get('extraction', {}).get('page_count')
                    for item in summary['source_extraction'])
    result = {**summary, 'schema': 'formatly.school-expansion.v1',
              'manifest_file_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              'institution_count': len({source['institution'] for source in manifest['sources']}),
              'source_count': len(manifest['sources']), 'source_formats': dict(Counter(
                  Path(source['original_filename']).suffix.lstrip('.').lower() for source in manifest['sources'])),
              'by_target': scores['by_target'], 'by_ruleset': by_ruleset, 'by_source': by_source,
              'source_candidate_metrics': source_metrics(manifest, summary['source_extraction']),
              'source_reading_complete': full_read, 'passed': summary['passed'] and full_read,
              'detection_passed': summary['detection_contracts_passed'],
              'source_candidate_scope': 'Full original input; recall only for independently locked selected clauses',
              'elapsed_seconds': round(time.perf_counter() - started, 6),
              'full_school_requirements_accepted': False}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--manifest', default=MANIFEST, type=Path)
    parser.add_argument('--source-cache', default=SOURCE_CACHE, type=Path)
    parser.add_argument('--download-sources', action='store_true')
    args = parser.parse_args()
    try:
        summary = run(args.output.resolve(), args.manifest.resolve(), args.source_cache.resolve(), fetch=args.download_sources)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps({key: summary[key] for key in ('passed', 'source_count', 'institution_count', 'sample_count',
                                                    'detection_passed', 'source_extraction_status',
                                                    'source_reading_complete', 'source_candidate_metrics', 'metrics')}, ensure_ascii=False))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
