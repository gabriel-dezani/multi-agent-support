from types import SimpleNamespace
import pytest
from app.rag.ranking import bm25_rank, hybrid_fuse
from app.evaluation.retrieval import (metrics_at_k, evaluate_retrieval_items, check_gates,
                                      normalize_source)


def document(id, content, source='https://www.getnet.net/en'):
    return SimpleNamespace(page_content=content,
                           metadata={'chunk_id': id, 'source_url': source})


def test_bm25_ranks_specific_evidence_and_ignores_irrelevant():
    docs = [document('a', 'Getnet Pix instant payment and QR'),
            document('b', 'terminal offline'), document('c', 'Pix QR Pix Pix')]
    ranked = bm25_rank('pix qr', docs)
    assert ranked[0][0].metadata['chunk_id'] == 'c'
    assert 'b' not in [x.metadata['chunk_id'] for x, _ in ranked]


def test_fusion_refuses_keyword_only_and_preserves_semantic_scores():
    a = document('a', 'pix payment')
    b = document('b', 'pix boleto')
    spam = document('spam', 'pix pix pix pix')
    combined = hybrid_fuse([(a, .8), (b, .6)], [(b, 99), (spam, 2), (a, 1)],
                           limit=4, min_dense_relevance=.45)
    assert [x.metadata['chunk_id'] for x, _ in combined] == ['b', 'a']
    assert [score for _, score in combined] == [.6, .8]


def test_source_diversity_and_dense_floor():
    docs = [document(str(i), 'pix', 'https://www.getnet.net/en') for i in range(4)]
    docs.append(document('other', 'pix', 'https://site.getnet.com.br/pix'))
    selected = hybrid_fuse([(d, .9) for d in docs], [],
                           limit=5, min_dense_relevance=.45, max_per_source=2)
    assert len(selected) == 5



def test_metrics_are_source_grounded_not_fabricated():
    gold = ['https://www.getnet.net/pix/']
    found = ['https://getnet.net/other', 'https://getnet.net/pix?ref=123']
    scores = metrics_at_k(gold, found, 2)
    assert scores['recall_at_k'] == 1.0
    assert scores['mrr'] == 0.5
    assert scores['hit_at_k'] == 1.0
    assert normalize_source('http://getnet.net/pix') == ''
    with pytest.raises(ValueError):
        metrics_at_k([], found, 2)


def test_errors_count_as_failures_and_gates_cannot_pass_tiny_datasets():
    items = [{'id': '1', 'question': 'pix', 'gold_source_urls': ['https://getnet.net/pix']},
             {'id': '2', 'question': 'terminal', 'gold_source_urls': ['https://getnet.net/term']}]
    def engine(q):
        if q == 'terminal':
            raise TimeoutError()
        return [(document('x','pix','https://getnet.net/pix'), .9)]
    report = evaluate_retrieval_items(items, engine, k=2)
    assert report['scores']['hit_at_k'] == .5
    assert report['cases'][1]['status'] == 'retrieval_error:TimeoutError'
    assert check_gates(report, {'hit_at_k': .95}, minimum_cases=5)
