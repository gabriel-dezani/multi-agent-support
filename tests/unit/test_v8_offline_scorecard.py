"""Checks that offline CI gates fail on regressions and never call external APIs."""
import json
from pathlib import Path
import pytest
from scripts.offline_quality_scorecard import calculate_scorecard


def test_offline_contracts_are_deterministic_and_no_cost():
    report=calculate_scorecard()
    assert report['status']=='pass'
    assert report['external_api_calls']==0
    assert report['human_verified_semantic_accuracy'] is None
    assert report['factuality_contract']['cases'] >= 20
    assert report['factuality_contract']['unsupported'] >= 8
    assert report['routing_contract']['cases'] >= 15


def test_tampered_grounding_fixture_makes_gate_fail(tmp_path):
    root=Path('.')
    (tmp_path/'data').mkdir()
    for name in ('offline_grounding_regressions.json','evaluation_dataset.json',
                 'evaluation_feedback_v6.json'):
        (tmp_path/'data'/name).write_bytes((root/'data'/name).read_bytes())
    path=tmp_path/'data/offline_grounding_regressions.json'
    dataset=json.loads(path.read_text(encoding='utf8'))
    dataset[0]['expected_supported']=False
    path.write_text(json.dumps(dataset,ensure_ascii=False),encoding='utf8')
    assert calculate_scorecard(tmp_path)['status']=='fail'
