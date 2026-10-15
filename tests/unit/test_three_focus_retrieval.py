from types import SimpleNamespace

import pytest

from app.evaluation.paired_retrieval import paired_report, ablation_gate, verify_reviewed_dataset


def _source(i):
    return 'https://site.getnet.com.br/section/' + str(i)


def _items(n=14):
    return [{'id':f'case-{i}', 'question': f'Getnet product details question {i}',
             'category':'pix' if i % 2 else 'terminal',
             'gold_source_urls':[_source(i)], 'reviewed_by':'QA Reviewer',
             'reviewed_at':'2025-01-01'} for i in range(n)]


def _retrieved(question, accurate=False):
    i = int(question.rsplit(' ', 1)[1])
    ranks = [_source(999), _source(i)] if not accurate else [_source(i), _source(999)]
    return [(SimpleNamespace(metadata={'source_url':u}), 0.8) for u in ranks]


def test_paired_report_reproducible_and_detects_gain():
    items = _items()
    report = paired_report(items, lambda q: _retrieved(q),
                           lambda q: _retrieved(q, accurate=True), k=2, seed=45)
    assert report['cases'] == 14
    assert report['metrics']['mrr']['dense'] == .5
    assert report['metrics']['mrr']['hybrid'] == 1.0
    assert report['metrics']['mrr']['delta'] == .5
    assert report['metrics']['mrr']['delta_ci95'] == [.5, .5]
    assert ablation_gate(report) == []
    assert report['limitations']


def test_paired_report_flags_regression_and_errors():
    items = _items()
    def failed(query):
        if query.endswith(' 0'):
            raise OSError('indexed data not ready')
        return _retrieved(query)
    report = paired_report(items,lambda q:_retrieved(q,accurate=True),failed,k=2)
    assert report['errors']['hybrid'] == 1
    assert 'retrieval_errors' in ablation_gate(report)
    assert 'hybrid_regressed_mrr' in ablation_gate(report)


@pytest.mark.parametrize('change', [
    lambda items: items[0].pop('reviewed_by'),
    lambda items: items[0].update(reviewed_at='2029-01-01'),
    lambda items: items[1].update(id=items[0]['id']),
    lambda items: items[0].update(gold_source_urls=['http://evil.local/private']),
    lambda items: items[0].update(gold_source_urls=['https://evil.example/fake-getnet']),
    lambda items: items[0].update(category=''),
    lambda items: items[0].update(question=items[1]['question']),
])
def test_dataset_fails_closed_without_provenance_or_distinct_cases(change):
    items = _items()
    change(items)
    with pytest.raises(ValueError):
        verify_reviewed_dataset(items)


def test_an_all_zero_retriever_cannot_pass_as_no_regression():
    items = _items()
    def none_found(query):
        return []
    report = paired_report(items, none_found, none_found)
    issues = ablation_gate(report)
    assert 'hybrid_recall_below_minimum' in issues
    assert 'hybrid_mrr_below_minimum' in issues


def test_global_good_metric_cannot_hide_single_category_regression():
    items = _items()
    def hybrid(q):
        return _retrieved(q, accurate=int(q.rsplit(' ', 1)[1]) % 2 == 0)
    report = paired_report(items, lambda q: _retrieved(q, accurate=True), hybrid, k=2)
    assert report['by_category']['pix']['metrics']['mrr']['dense'] == 1.0
    assert 'category_regression:pix:mrr' in ablation_gate(report)
