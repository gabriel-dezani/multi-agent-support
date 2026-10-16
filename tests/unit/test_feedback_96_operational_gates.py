"""Operational gates use persisted rolling-window evidence, not screenshots.

No network, OpenAI, Tavily or external collector is used.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from app.core.telemetry import TelemetryRepository
from app.core.observability import evaluate_operational_gates, evaluate_slo
from app.evaluation.calibration import calibration_metrics, calibration_gate


def _record(repo, *, error=False, degraded=False, fallback=False, handoff=False,
            usage_complete=True, latency_ms=100):
    request_id = str(uuid4())
    repo.record(request_id=request_id, user_ref='hash-only', route='knowledge',
                latency_ms=latency_ms, escalated=handoff, degraded=degraded,
                spans=[], agents=['knowledge'], status_code=503 if error else 200,
                routing_strategy='deterministic_fallback_after_error' if fallback else 'llm_structured_plan',
                usage_complete=usage_complete)
    return request_id


def test_recent_stats_excludes_outdated_rows_and_preserves_raw_counts(tmp_path):
    repo = TelemetryRepository(tmp_path / 'telemetry.db')
    recent = _record(repo, error=True, degraded=True, fallback=True, latency_ms=300)
    old = _record(repo, error=False, degraded=False, latency_ms=1)
    # Force a historical event; all alert denominators must share the window.
    with sqlite3.connect(repo.path) as conn:
        conn.execute('UPDATE request_stats SET created_at=datetime(\'now\',\'-2 days\') WHERE request_id=?', (old,))
    stats = repo.recent_stats(window_minutes=60)
    assert stats['requests'] == 1
    assert stats['errors'] == 1
    assert stats['degraded'] == 1
    assert stats['routing_fallback_errors'] == 1
    assert stats['latency_p95_ms'] == 300
    assert repo.stats()['requests'] == 2
    assert evaluate_operational_gates(stats)['status'] == 'insufficient_data'


def test_operational_alert_on_recent_provider_outage_not_hidden_by_lifetime_success(tmp_path):
    repo = TelemetryRepository(tmp_path / 'incidents.db')
    ids = [_record(repo, latency_ms=50) for _ in range(30)]
    with sqlite3.connect(repo.path) as conn:
        conn.executemany('UPDATE request_stats SET created_at=datetime(\'now\',\'-2 days\') WHERE request_id=?',[(x,) for x in ids])
    for _ in range(29):
        _record(repo, latency_ms=100)
    _record(repo, error=True, degraded=True, fallback=True, latency_ms=8000)
    current = repo.recent_stats(window_minutes=60)
    assert current['requests'] == 30
    assert current['errors'] == 1
    # Example: degraded threshold intentionally stricter than error SLO.
    alarm = evaluate_operational_gates(current, max_degraded_rate=.02)
    assert alarm['status'] == 'alert'
    assert 'degradation_rate' in alarm['alerts']
    assert alarm['checks']['usage_completeness'] is True
    assert evaluate_slo(current)['status'] == 'pass'  # 1/30 < 5% and p95 < 5s


def test_an_unhealthy_service_cannot_pass_with_missing_alert_metrics():
    report = evaluate_operational_gates({'requests': 35, 'errors': 0, 'degraded': 0,
        'latency_p95_ms': 100, 'usage_evaluated_requests': 10, 'usage_complete_requests': 0})
    assert report['status'] == 'alert'
    assert 'usage_completeness' in report['alerts']
    assert 'router_provider_error_rate' in report['missing_metrics']
    assert report['checks']['usage_completeness'] is False


def test_legitimate_handoffs_are_not_scored_as_provider_incidents():
    data = {'window_minutes':60,'requests':40,'errors':0,'degraded':0,'routing_fallback_errors':0,
            'latency_p95_ms':120,'human_escalations':40,
            'usage_evaluated_requests':40,'usage_complete_requests':40}
    report = evaluate_operational_gates(data)
    assert report['status'] == 'healthy'
    assert report['human_escalations'] == 40


@pytest.mark.parametrize('window', [True, 0, 4, 1441, 60.0, '60'])
def test_window_is_bounded_and_type_checked(tmp_path, window):
    repo = TelemetryRepository(tmp_path / 'check.db')
    with pytest.raises(ValueError):
        repo.recent_stats(window_minutes=window)


def test_awareness_required_for_fixed_time(tmp_path):
    repo = TelemetryRepository(tmp_path / 'tz.db')
    with pytest.raises(ValueError):
        repo.recent_stats(now=datetime(2026,1,1))
    assert repo.recent_stats(now=datetime.now(timezone.utc))['requests'] == 0


def test_calibration_cannot_pass_by_rejecting_every_supported_answer():
    human = [{'human_supported': True, 'judge_supported': False} for _ in range(16)]
    human += [{'human_supported': False, 'judge_supported': False} for _ in range(16)]
    metrics = calibration_metrics(human)
    assert metrics['false_accept_rate'] == 0
    assert metrics['recall'] == 0
    flags = calibration_gate(metrics)
    assert 'Judge rejects too many supported answers' in flags


def test_calibration_needs_both_positive_and_negative_cases():
    all_negative = calibration_metrics([
        {'human_supported':False,'judge_supported':False} for _ in range(30)])
    assert 'Insufficient supported-answer cases' in calibration_gate(all_negative)
    good = calibration_metrics([
        *[{'human_supported':True,'judge_supported':True} for _ in range(12)],
        *[{'human_supported':False,'judge_supported':False} for _ in range(12)]])
    assert calibration_gate(good) == []


def test_invalid_quality_gate_thresholds_fail_closed():
    with pytest.raises(ValueError):
        evaluate_operational_gates({}, max_error_rate=float('nan'))
    with pytest.raises(ValueError):
        evaluate_operational_gates({}, minimum_samples=0)
    with pytest.raises(ValueError):
        calibration_gate({}, min_supported_recall=float('inf'))
