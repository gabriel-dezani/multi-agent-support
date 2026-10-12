"""Fast offline regressions independent of external LLM/vector dependencies."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.api.schemas import ChatRequest
from app.core import auth
from app.core.telemetry import TelemetryRepository
from app.core.usage import add_usage, cost_usd
from app.handoff.repository import HandoffRepository
from app.memory.store import ConversationMemoryStore
from app.orchestration.review_policy import choose_next, prepare_review


def _settings():
    return SimpleNamespace(api_credentials_json=json.dumps({
        'alice-demo-token': {'user_id': 'alice', 'role': 'customer'},
        'bob-demo-token': {'user_id': 'bob', 'role': 'customer'},
        'operator-demo-token': {'user_id': 'operator', 'role': 'operator'}
    }))


def test_identity_matches_declared_user(monkeypatch):
    monkeypatch.setattr(auth, 'get_settings', _settings)
    subject = auth.resolve_identity('Bearer alice-demo-token')
    auth.assert_customer(subject, 'alice')
    with pytest.raises(HTTPException) as exc:
        auth.assert_customer(subject, 'bob')
    assert exc.value.status_code == 403


@pytest.mark.parametrize('authorization,expected', [
    (None,401),('Bearer wrong',401),('token alice-demo-token',401),
    ('Bearer ',401)
])
def test_credentials_fail_closed(monkeypatch, authorization, expected):
    monkeypatch.setattr(auth, 'get_settings', _settings)
    with pytest.raises(HTTPException) as exc:
        auth.resolve_identity(authorization)
    assert exc.value.status_code == expected


def test_empty_identity_config_refuses_all(monkeypatch):
    monkeypatch.setattr(auth,'get_settings',lambda: SimpleNamespace(api_credentials_json='{}'))
    with pytest.raises(HTTPException) as exc:
        auth.resolve_identity('Bearer alice-demo-token')
    assert exc.value.status_code == 503


def test_operator_cannot_claim_customer(monkeypatch):
    monkeypatch.setattr(auth, 'get_settings', _settings)
    with pytest.raises(HTTPException) as exc:
        auth.assert_customer(auth.resolve_identity('Bearer operator-demo-token'),'operator')
    assert exc.value.status_code == 403


def test_chat_request_forbids_extra_identity_fields():
    with pytest.raises(ValidationError):
        ChatRequest(message='hello', user_id='alice', role='operator')


def test_messages_isolate_identical_conversation_ids(tmp_path):
    store=ConversationMemoryStore(str(tmp_path/'state.db'))
    store.append_turn('shared-id','alice','hi','alice answer','r1')
    store.append_turn('shared-id','bob','hi','bob answer','r2')
    assert [x['content'] for x in store.get_history('shared-id','alice')] == ['hi','alice answer']
    assert [x['content'] for x in store.get_history('shared-id','bob')] == ['hi','bob answer']


def test_ticket_issuance_is_concurrency_safe(tmp_path):
    repo=HandoffRepository(str(tmp_path/'state.db'))
    def create(i):
        return repo.create(request_id=f'req-{i}',conversation_id='same',user_id='alice',
                           reason='support',summary='summary')['handoff_id']
    with ThreadPoolExecutor(max_workers=12) as pool:
        ids=list(pool.map(create,range(30)))
    assert len(set(ids)) == 1
    assert len(repo.list('pending')) == 1


def test_atomic_resolution_writes_human_reply_once(tmp_path):
    path=str(tmp_path/'state.db')
    store=ConversationMemoryStore(path)
    repo=HandoffRepository(path)
    record=repo.create(request_id='req1',conversation_id='conv',user_id='alice',reason='help',summary='x')
    one=repo.resolve(record['handoff_id'],resolution='human answer',resolved_by='op',append_memory=True)
    two=repo.resolve(record['handoff_id'],resolution='other answer',resolved_by='op',append_memory=True)
    assert one['_transitioned'] is True
    assert two['_transitioned'] is False
    assert [v['content'] for v in store.get_history('conv','alice')] == ['human answer']


def test_handoff_ownership_isolation(tmp_path):
    repo=HandoffRepository(str(tmp_path/'state.db'))
    repo.create(request_id='r1',conversation_id='same',user_id='alice',reason='help',summary='x')
    assert repo.user_cases('same','bob') == []
    assert len(repo.user_cases('same','alice')) == 1


def test_supervisor_continues_when_first_specialist_fails():
    state={'plan':['knowledge','customer_support'],'current_step':1,'agent_results':[
        {'agent':'knowledge','requires_human':True}]}
    assert choose_next(state) == 'customer_support'
    state['current_step']=2
    state['agent_results'].append({'agent':'customer_support','requires_human':False})
    assert choose_next(state)=='human_escalation'
    assert prepare_review(state)['unresolved_agents']==['knowledge']


def test_supervisor_synthesizes_all_successes():
    assert choose_next({'plan':['knowledge','customer_support'], 'current_step':2,
                        'agent_results':[{'requires_human':False},{'requires_human':False}]})=='synthesis'


def test_telemetry_persists_and_ratings_are_owned(tmp_path):
    path=str(tmp_path/'state.db')
    stats=TelemetryRepository(path)
    stats.record(request_id='request-001',user_ref='hashed-alice',route='knowledge',
                 latency_ms=33,escalated=False,degraded=False,spans=[
                     {'agent':'knowledge','duration_ms':29,'status':'ok'}],
                 usage={'input_tokens':34,'output_tokens':12},retrieval={'hits':3,'max_score':0.87})
    assert not stats.rate('request-001','hashed-bob',5)
    assert stats.rate('request-001','hashed-alice',5)
    other=TelemetryRepository(path)
    assert other.trace('request-001')[0]['agent']=='knowledge'
    overview=other.stats()
    assert overview['requests']==1
    assert overview['input_tokens_reported']==34
    assert overview['feedback_count']==1
    assert overview['avg_retrieval_hits_reported']==3
    assert overview['avg_retrieval_best_score_reported']==0.87


def test_missing_usage_is_unknown_not_zero():
    assert add_usage({}, {})=={}
    assert add_usage({'input_tokens':2,'output_tokens':3},{'input_tokens':5,'output_tokens':7})=={'input_tokens':7,'output_tokens':10}
    assert cost_usd({}) is None
