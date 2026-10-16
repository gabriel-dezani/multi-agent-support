import json
from pathlib import Path

from scripts.offline_supervisor_scorecard import evaluate_cases


def _cases():
    return json.loads((Path(__file__).resolve().parents[2] /
                       'data/supervisor_policy_regressions.json').read_text(encoding='utf8'))


def test_supervisor_offline_regressions_pass_all_22_developer_cases():
    report = evaluate_cases(_cases())
    assert report['status'] == 'pass'
    assert report['cases'] == 22
    assert not report['failures']
    assert report['external_api_calls'] == 0
    assert report['human_reviewed'] is False


def test_supervisor_gate_reports_regressions_not_just_case_count():
    cases = _cases()
    cases[0]['expected_next'] = 'synthesis'
    report = evaluate_cases(cases)
    assert report['status'] == 'fail'
    assert report['failures'][0]['id'] == cases[0]['id']
