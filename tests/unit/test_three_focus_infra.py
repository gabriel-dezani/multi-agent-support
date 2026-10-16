from types import SimpleNamespace

import pytest

from app.core.distributed_lock import advisory_key
from app.core.readiness import validate_deployment
from app.core.postgres_state import PgSession


def test_advisory_keys_scoped_and_unambiguous():
    assert advisory_key('a','bc') != advisory_key('ab','c')
    assert advisory_key('alice','same') != advisory_key('bob','same')
    assert advisory_key('alice','same') == advisory_key('alice','same')
    assert -(2**63) <= advisory_key('a','b') <= 2**63-1


def _settings(**changes):
    config = dict(app_env='development',state_backend='sqlite',state_database_url='',replicas=1)
    config.update(changes)
    return SimpleNamespace(**config)


def test_multiple_replicas_fail_closed_with_sqlite():
    with pytest.raises(RuntimeError,match='PostgreSQL'):
        validate_deployment(_settings(replicas=2))


def test_multiple_replicas_fail_closed_without_external_vector_index():
    with pytest.raises(RuntimeError,match='vector service'):
        validate_deployment(_settings(replicas=2,state_backend='postgres',
                                      state_database_url='postgresql://localhost/app'))


def test_postgres_requires_explicit_url_even_in_development():
    with pytest.raises(RuntimeError,match='STATE_DATABASE_URL'):
        validate_deployment(_settings(state_backend='postgres'))


def test_parameter_adapter_does_not_interpolate_values():
    executed = []
    class Cursor:
        rowcount = 1
        description = []
    class Connection:
        def execute(self, query, arguments):
            executed.append((query,arguments))
            return Cursor()
    sql = "SELECT * FROM handoffs WHERE user_id=? AND summary=?"
    param = "user' OR 1=1 --"
    PgSession(Connection()).execute(sql, (param,'? literal value'))
    assert executed == [("SELECT * FROM handoffs WHERE user_id=%s AND summary=%s",
                         (param,'? literal value'))]
