"""Quality gate calculations with fixtures only, no network or model."""
import pytest
from scripts.evaluate_grounding_local import evaluate_reviewed_dataset


def case(i, expected, answer, evidence):
    return {'id': str(i), 'answer':answer, 'evidence':[evidence],
            'sources':['https://site.getnet.com.br/pix/'],
            'human_supported':expected,'reviewed_by':'fixture-only'}


def test_human_labeled_eval_detects_false_accepts():
    items=[case(i, False, 'Informação sobre Pix.', 'Atenção: crédito.') for i in range(10)]
    # A purely lexical/numeric heuristic misses the invented statement. This
    # demonstrates why the synthetic passing gate does not prove semantics.
    report=evaluate_reviewed_dataset(items,min_cases=10,min_negatives=8)
    assert report['scores']['false_accepts']==10
    assert report['scores']['false_accept_rate']==1
    assert report['violations']
    assert report['external_api_calls']==0


def test_reviewer_and_label_are_mandatory():
    item=case(1,True,'Pix','Pix')
    item.pop('reviewed_by')
    with pytest.raises(ValueError,match='reviewed_by'):
        evaluate_reviewed_dataset([item],min_cases=1,min_negatives=1)


def test_local_gate_passes_when_failures_are_detected():
    items=[case(i,False,'Taxa de 10%.','Taxa de 2%.') for i in range(9)]
    items += [case(i,True,'Taxa de 2%.','Taxa de 2%.') for i in range(9,20)]
    report=evaluate_reviewed_dataset(items)
    assert report['scores']['samples']==20
    assert report['scores']['false_accept_rate']==0
    assert not report['violations']
