"""Authenticated local operations endpoints with real SQLite, no paid API."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('structlog')

from fastapi.testclient import TestClient

import app.api.routes as routes
import app.core.security as security
from app.core.telemetry import TelemetryRepository
from app.main import app


def test_operator_only_can_query_utc_window_alerts(monkeypatch, tmp_path):
    repo = TelemetryRepository(tmp_path / 'ops.db')
    settings = SimpleNamespace(auth_mode='local', operator_token='local-ops-token')
    monkeypatch.setattr(routes, '_telemetry', repo)
    monkeypatch.setattr(routes, 'get_settings', lambda: settings)
    monkeypatch.setattr(security, 'get_settings', lambda: settings)
    for _ in range(35):
        repo.record(request_id=str(uuid4()), user_ref='hashed-only', route='knowledge',
                    latency_ms=120, escalated=False, degraded=False, spans=[],
                    agents=['knowledge'], status_code=200, usage_complete=True)
    client = TestClient(app)
    assert client.get('/ops/alerts').status_code == 403
    assert client.get('/ops/alerts', headers={'X-Operator-Token':'wrong'}).status_code == 403
    headers = {'X-Operator-Token':'local-ops-token'}
    response = client.get('/ops/alerts?window_minutes=60', headers=headers)
    assert response.status_code == 200
    assert response.json()['status'] == 'healthy'
    assert response.json()['sample_count'] == 35
    assert 'user_ref' not in response.text
    assert client.get('/ops/alerts?window_minutes=1', headers=headers).status_code == 422
    slo = client.get('/ops/slo?window_minutes=60', headers=headers)
    assert slo.status_code == 200
    assert slo.json()['status'] == 'pass'
