"""Fair A/B retrieval comparison on the SAME manually reviewed questions.

Reports paired macro metric differences plus percentile bootstrap uncertainty.
No models, network, side effects or gold answers are generated in this module.
An all-zero or cherry-picked label set never implies general factual quality.
"""
import random
from collections import Counter
from datetime import date
from urllib.parse import urlsplit

from app.evaluation.retrieval import metrics_at_k

METRICS = ('recall_at_k', 'precision_at_k', 'mrr', 'ndcg_at_k', 'hit_at_k')


def verify_reviewed_dataset(items: list[dict], *, minimum: int = 10) -> None:
    if not isinstance(items, list) or len(items) < minimum:
        raise ValueError(f'At least {minimum} labeled cases required')
    seen = set()
    questions = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid dataset case')
        identifier = item.get('id')
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError('Case IDs must be unique and nonempty')
        seen.add(identifier)
        if not isinstance(item.get('question'), str) or not item['question'].strip():
            raise ValueError('Every case needs a question')
        q = item['question'].strip().casefold()
        if q in questions:
            raise ValueError('Duplicate questions cannot inflate the sample count')
        questions.add(q)
        sources = item.get('gold_source_urls')
        if not isinstance(sources, list) or not sources:
            raise ValueError('Every case needs reviewed gold sources')
        # The existing source sanitizer rejects non-HTTPS or malformed labels.
        from app.evaluation.retrieval import normalize_source
        allowed_hosts = {'getnet.net', 'www.getnet.net', 'site.getnet.com.br'}
        if any(not isinstance(v, str) or not normalize_source(v)
               or urlsplit(v).hostname not in allowed_hosts for v in sources):
            raise ValueError('Gold sources must be official, valid HTTPS Getnet URLs')
        reviewer, reviewed = item.get('reviewed_by'), item.get('reviewed_at')
        if not isinstance(reviewer, str) or len(reviewer.strip()) < 3:
            raise ValueError('Human reviewer identity is required')
        if not isinstance(reviewed, str):
            raise ValueError('Human review date is required')
        try:
            if date.fromisoformat(reviewed) > date.today():
                raise ValueError('Review cannot be dated in the future')
        except ValueError as exc:
            raise ValueError('Review date must be ISO YYYY-MM-DD, not future') from exc
        if not isinstance(item.get('category'), str) or not item['category'].strip():
            raise ValueError('Each item needs a category for stratified reporting')
    if len({x['question'].strip().casefold() for x in items}) < minimum:
        raise ValueError('Duplicate questions cannot inflate the sample count')


def _mean(items, key):
    return round(sum(row[key] for row in items) / len(items), 4)


def paired_report(items: list[dict], dense_retrieve, hybrid_retrieve, *, k=4,
                  minimum=10, draws=1000, seed=42) -> dict:
    """Fail closed: any retrieval exception is recorded as a zero score.

    This function makes no human-review claims itself; it requires audit metadata
    but cannot independently authenticate an external reviewer's identity.
    """
    if k < 1 or draws < 100:
        raise ValueError('k must be positive and bootstrap draws >=100')
    verify_reviewed_dataset(items, minimum=minimum)
    cases = []
    for case in items:
        output = {'id': case['id'], 'category': case['category']}
        for name, retrieve in (('dense', dense_retrieve), ('hybrid', hybrid_retrieve)):
            try:
                rows = retrieve(case['question'])
                urls = [doc.metadata.get('source_url', '') for doc, _ in rows[:k]]
                values = metrics_at_k(case['gold_source_urls'], urls, k)
                output[name] = {metric: values[metric] for metric in METRICS}
                output[name + '_status'] = 'ok'
            except Exception as exc:
                output[name] = {metric: 0.0 for metric in METRICS}
                output[name + '_status'] = 'error:' + type(exc).__name__
        cases.append(output)
    rng = random.Random(seed)
    metrics = {}
    for metric in METRICS:
        delta = [c['hybrid'][metric] - c['dense'][metric] for c in cases]
        boot = sorted(sum(delta[rng.randrange(len(delta))] for _ in delta) / len(delta)
                      for _ in range(draws))
        metrics[metric] = {
            'dense': _mean([c['dense'] for c in cases], metric),
            'hybrid': _mean([c['hybrid'] for c in cases], metric),
            'delta': round(sum(delta) / len(delta), 4),
            'delta_ci95': [round(boot[int(draws * .025)], 4),
                           round(boot[min(draws - 1, int(draws * .975))], 4)],
        }
    categories = {}
    for category in sorted(set(c['category'] for c in cases)):
        subset = [c for c in cases if c['category'] == category]
        categories[category] = {
            'count': len(subset),
            'metrics': {metric: {
                'dense': _mean([c['dense'] for c in subset], metric),
                'hybrid': _mean([c['hybrid'] for c in subset], metric),
            } for metric in METRICS},
        }
    return {
        'cases': len(cases), 'categories': dict(Counter(c['category'] for c in cases)),
        'by_category': categories,
        'method': 'paired-source-recall-with-bootstrap',
        'limitations': 'Manual review metadata is not cryptographically verified; retrieval does not prove factual answer quality',
        'metrics': metrics, 'errors': {name: sum(c[name + '_status'] != 'ok' for c in cases)
                                      for name in ('dense', 'hybrid')},
        'cases_detail': cases,
    }


def ablation_gate(report: dict, *, minimum=10, max_regression=.02,
                  max_errors=0, minimum_categories=2,
                  minimum_recall=.75, minimum_mrr=.70,
                  minimum_category_cases=3) -> list[str]:
    issues = []
    if report['cases'] < minimum:
        issues.append('too_few_reviewed_cases')
    if len(report['categories']) < minimum_categories:
        issues.append('too_few_categories')
    if report['errors']['dense'] > max_errors or report['errors']['hybrid'] > max_errors:
        issues.append('retrieval_errors')
    for metric in METRICS:
        if report['metrics'][metric]['delta'] < -max_regression:
            issues.append('hybrid_regressed_' + metric)
    # An unchanged but ineffective retriever must NEVER pass this gate.
    if report['metrics']['recall_at_k']['hybrid'] < minimum_recall:
        issues.append('hybrid_recall_below_minimum')
    if report['metrics']['mrr']['hybrid'] < minimum_mrr:
        issues.append('hybrid_mrr_below_minimum')
    # A strong global average cannot conceal a seriously regressed category.
    for category, result in report.get('by_category', {}).items():
        if result['count'] < minimum_category_cases:
            issues.append('insufficient_category_examples:' + category)
        for metric in ('recall_at_k', 'mrr'):
            scores = result['metrics'][metric]
            if scores['hybrid'] < scores['dense'] - max_regression:
                issues.append('category_regression:' + category + ':' + metric)
    return issues
