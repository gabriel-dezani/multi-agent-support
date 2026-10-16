"""A depleted provider balance must not create a bogus human support ticket.

Entirely simulated; no OpenAI/Tavily requests and no paid model usage.
"""
import json
import pytest

pytest.importorskip('langgraph')
pytest.importorskip('structlog')
pytest.importorskip('langchain_core')

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.main import app
from app.core.config import get_settings
from app.core.upstream import UpstreamUnavailable
from app.core.telemetry import TelemetryRepository
from app.handoff.repository import HandoffRepository
from app.memory.store import ConversationMemoryStore
from app.agents.knowledge import KnowledgeAgent
import app.api.routes as routes


class SimulatedOutage:
    async def ainvoke(self, state):
        raise UpstreamUnavailable('simulated provider budget outage')


class FakeRetriever:
    def retrieve(self, query):
        return [(Document(page_content='Getnet Pix oficial.',
                          metadata={'source_url':'https://site.getnet.com.br/pix/'}), .91)]


class FakeProviderError(Exception):
    code = 'credit_balance_exhausted'
    body = {'error': {'code': 'credit_balance_exhausted'}}


class FakeLLM:
    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        raise FakeProviderError('simulated provider billing failure')


def test_provider_failure_is_503_without_memory_or_ticket(monkeypatch, tmp_path):
    monkeypatch.setenv('API_CREDENTIALS_JSON', json.dumps({
        'no-cost-test-token': {'user_id':'cliente1988','role':'customer'}
    }))
    get_settings.cache_clear()
    store_path = str(tmp_path / 'service.db')
    memory = ConversationMemoryStore(store_path)
    handoffs = HandoffRepository(store_path)
    monkeypatch.setattr(routes, '_graph', SimulatedOutage())
    monkeypatch.setattr(routes, '_memory', memory)
    monkeypatch.setattr(routes, '_handoffs', handoffs)
    monkeypatch.setattr(routes, '_telemetry', TelemetryRepository(str(tmp_path / 'telemetry.db')))
    reply = TestClient(app).post('/chat', headers={'Authorization':'Bearer no-cost-test-token'},
        json={'message':'Explique o Pix','user_id':'cliente1988','conversation_id':'v8-outage'})
    assert reply.status_code == 503
    assert 'temporariamente indisponível' in reply.json()['detail']
    assert reply.headers['X-Request-ID']
    assert memory.get_history('v8-outage','cliente1988') == []
    assert handoffs.pending('v8-outage','cliente1988') is None
    get_settings.cache_clear()


def test_knowledge_quota_exception_is_technical_not_handoff():
    agent = KnowledgeAgent(retriever=FakeRetriever(), llm=FakeLLM())
    with pytest.raises(UpstreamUnavailable):
        agent.process('Como funciona o Pix?')
