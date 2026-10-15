import pytest
from app.evaluation.calibration import calibration_metrics, calibration_gate


def test_semantic_judge_false_acceptance_gate():
    items=[{'human_supported':False,'judge_supported':True} for _ in range(2)]
    items += [{'human_supported':False,'judge_supported':False} for _ in range(18)]
    items += [{'human_supported':True,'judge_supported':True} for _ in range(20)]
    scores=calibration_metrics(items)
    assert scores['false_accept_rate'] == .1
    assert scores['precision'] == .9091
    assert calibration_gate(scores, min_total=20,min_negative=8,max_false_accept_rate=.05)


def test_no_negative_examples_is_not_a_success():
    scores=calibration_metrics([{'human_supported':True,'judge_supported':True} for _ in range(30)])
    assert scores['false_accept_rate'] is None
    assert calibration_gate(scores)
    with pytest.raises(ValueError):
        calibration_metrics([{'human_supported':'yes','judge_supported':True}])
