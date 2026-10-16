from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
import sqlite3
import pytest
from app.memory.store import ConversationMemoryStore
from app.core.readiness import validate_deployment, check_readiness


def test_retention_culls_expired_only_and_is_opt_in(tmp_path):
    store=ConversationMemoryStore(str(tmp_path/'state.db'))
    store.append_turn('one','user','old','old answer','r1')
    store.append_turn('two','other','new','new answer','r2')
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE conversation_messages SET created_at=datetime('now','-60 days') WHERE conversation_id='one'")
    assert store.purge_expired(0) == 0
    assert store.purge_expired(30) == 2
    assert len(store.get_history('two','other')) == 2
    assert store.get_history('one','user') == []
    with pytest.raises(ValueError):
        store.purge_expired(-1)


def test_prod_requires_verified_auth_tracing_and_fact_checks():
    settings=SimpleNamespace(app_env='production',auth_mode='local',
        oidc_jwks_url='',oidc_issuer='',oidc_audience='',rag_verifier_mode='heuristic',
        otlp_endpoint='')
    with pytest.raises(RuntimeError, match='OIDC|oidc'):
        validate_deployment(settings)
    settings.app_env='development'
    validate_deployment(settings)


def test_readiness_checks_state_and_vector_dir(tmp_path):
    settings=SimpleNamespace(state_db_path=str(tmp_path/'state.db'),
                             vector_store_path=str(tmp_path/'vectors'))
    assert not check_readiness(settings)
    (tmp_path/'vectors').mkdir()
    store=ConversationMemoryStore(settings.state_db_path)
    assert not check_readiness(settings)  # memory alone is not operational readiness
    from app.handoff.repository import HandoffRepository
    from app.core.telemetry import TelemetryRepository
    HandoffRepository(settings.state_db_path)
    TelemetryRepository(settings.state_db_path)
    assert check_readiness(settings)
