"""Assess the free heuristic factuality gate against genuinely human-labeled cases.

Uses only local JSON and Python. Does not import any OpenAI client and does
not infer human truth from citations or a model judge. Unreviewed cases fail.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path

from app.evaluation.calibration import calibration_gate, calibration_metrics
from app.rag.verification import verify_claims

log = logging.getLogger(__name__)


def evaluate_reviewed_dataset(dataset: list[dict], *, min_cases: int = 20,
                              min_negatives: int = 8, min_positives: int = 8,
                              max_false_accept: float = .05,
                              min_supported_recall: float = .70) -> dict:
    if not isinstance(dataset, list):
        raise ValueError('A JSON list of human-reviewed cases is required')
    seen = set()
    judged = []
    for item in dataset:
        if not isinstance(item, dict):
            raise ValueError('Cases must be JSON objects')
        identifier = item.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError('Case IDs must be unique and non-empty')
        seen.add(identifier)
        truth = item.get('human_supported')
        reviewer = item.get('reviewed_by')
        if type(truth) is not bool or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError('Human support label and reviewed_by are mandatory')
        answer, evidence, sources = item.get('answer'), item.get('evidence'), item.get('sources', [])
        if not isinstance(answer, str) or not isinstance(evidence, list) or not evidence or \
                not all(isinstance(x, str) for x in evidence):
            raise ValueError('Answer and nonempty evidence array required')
        if not isinstance(sources, list) or not all(isinstance(x, str) for x in sources):
            raise ValueError('Sources must be an array of strings')
        verdict, reasons = verify_claims(answer, evidence, sources)
        judged.append({'id': identifier, 'human_supported': truth,
                       'judge_supported': verdict, 'rejection_reasons': reasons})
    scores = calibration_metrics(judged)
    problems = calibration_gate(scores, min_total=min_cases,
                min_negative=min_negatives, min_positive=min_positives,
                max_false_accept_rate=max_false_accept,
                min_supported_recall=min_supported_recall)
    return {'mode': 'offline_heuristic_human_labeled', 'external_api_calls': 0,
            'scores': scores, 'violations': problems, 'cases': judged,
            'limitation': ('Measures the conservative local heuristic against supplied human labels; '
                           'does not measure OpenAI response quality or prove general semantic entailment.')}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--dataset', required=True)
    cli.add_argument('--output', default='offline_grounding_review.json')
    cli.add_argument('--min-cases', type=int, default=20)
    cli.add_argument('--min-negatives', type=int, default=8)
    cli.add_argument('--min-positives', type=int, default=8)
    cli.add_argument('--min-supported-recall', type=float, default=.70)
    cli.add_argument('--max-false-accept', type=float, default=.05)
    args = cli.parse_args()
    if args.min_cases < 1 or args.min_negatives < 1 or args.min_positives < 1 or not 0 <= args.max_false_accept <= 1 or not 0 <= args.min_supported_recall <= 1:
        cli.error('Invalid quality gate thresholds')
    raw = Path(args.dataset).read_bytes()
    report = evaluate_reviewed_dataset(json.loads(raw), min_cases=args.min_cases,
             min_negatives=args.min_negatives, min_positives=args.min_positives,
             max_false_accept=args.max_false_accept, min_supported_recall=args.min_supported_recall)
    report['dataset_sha256'] = hashlib.sha256(raw).hexdigest()
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n',encoding='utf8')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    log.info('Offline human-reviewed grounding calibration: %s', json.dumps({
        'scores':report['scores'], 'violations':report['violations']},ensure_ascii=False))
    if report['violations']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
