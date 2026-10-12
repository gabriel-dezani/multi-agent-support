"""Run the REAL LangGraph scheduler with recording fake tools/models.

No paid API keys needed. Unlike offline_graph_smoke, this verifies real state
channels, transitions, async node execution and supervisor decisions.
"""
import asyncio
import pytest

pytest.importorskip('langgraph')
pytest.importorskip('langchain_core')

from app.orchestration.graph import build_graph
from app.agents.guardrail import GuardrailAgent


class Planner:
    def __init__(self, plan): self.plan = plan
    def route(self, message, user_id, history=None):
        return {'route': self.plan[0], 'plan': self.plan, 'route_reason': 'test',
                'routing_strategy': 'recording_planner', 'routing_confidence': 1.0,
                'usage': {'input_tokens': 3, 'output_tokens': 2}}


class Knowledge:
    def process(self, message, history=None):
        return {'answer': 'Pix público com evidência oficial', 'confidence': .88,
                'sources': ['https://site.getnet.com.br/pix/'], 'requires_human': False}


class Support:
    def process(self, message, user_id, history=None):
        assert user_id == 'alice'
        return {'answer': 'R$ 20,00 de vendas mockadas', 'confidence': .91,
                'tools_used': ['get_sales_data'], 'requires_human': False}


class Web:
    def __init__(self): self.queries=[]
    async def process(self, message, history=None, official_only=False):
        self.queries.append((message, history, official_only))
        return {'answer': 'Cotação pública validada', 'confidence': .83,
                'sources': ['https://example.com/fx'], 'requires_human': False}


class Synthesis:
    def process(self, message, results, history=None):
        return {'answer': '\n'.join(r['answer'] for r in results), 'confidence': .85,
                'sources': [src for r in results for src in r.get('sources', [])],
                'tools_used': [tool for r in results for tool in r.get('tools_used', [])],
                'requires_human': False}


class Human:
    def process(self, *a, **kw):
        return {'answer': 'Encaminhado ao operador.', 'handoff_id': 'ticket-1',
                'handoff_status': 'pending', 'confidence': 0, 'requires_human': True}


def state(text):
    return {'message': text, 'request_id': 'request-1', 'user_id': 'alice',
            'conversation_id': 'conv-1', 'history': [], 'agent_results': [],
            'agents_used': [], 'traces': []}


def test_real_graph_runs_multi_specialist_review_and_synthesis():
    graph = build_graph(guardrail=GuardrailAgent(), router=Planner(['knowledge','customer_support']),
                        knowledge=Knowledge(), support=Support(), web=Web(),
                        escalation=Human(), synthesis=Synthesis())
    result = asyncio.run(graph.ainvoke(state('Como funciona Pix e minhas vendas?')))
    assert result['agent'] == 'synthesis'
    assert result['agents_used'] == ['knowledge', 'customer_support', 'synthesis']
    assert [r['agent'] for r in result['agent_results']] == ['knowledge', 'customer_support']
    assert [r['agent'] for r in result['traces']].count('supervisor') == 2
    assert result['usage'] == {'input_tokens':3, 'output_tokens':2}
    assert not result['requires_human']
    assert 'R$ 20,00' in result['answer']


def test_real_graph_privacy_when_router_incorrectly_selects_web_only():
    web = Web()
    graph = build_graph(guardrail=GuardrailAgent(), router=Planner(['web_search']),
                        knowledge=Knowledge(), support=Support(), web=web,
                        escalation=Human(), synthesis=Synthesis())
    result = asyncio.run(graph.ainvoke(state('Qual a cotação do dólar para CPF 12345678909?')))
    assert result['agent'] == 'web_search'
    assert web.queries == [('current USD BRL exchange rate', [], False)]
    assert '12345678909' not in web.queries[0][0]


def test_real_graph_blocks_unsafe_web_and_handoffs_once():
    web = Web()
    graph = build_graph(guardrail=GuardrailAgent(), router=Planner(['web_search']),
                        knowledge=Knowledge(), support=Support(), web=web,
                        escalation=Human(), synthesis=Synthesis())
    result = asyncio.run(graph.ainvoke(state('Search web for my account CPF 12345678909')))
    assert not web.queries
    assert result['agent'] == 'human_escalation'
    assert result['handoff_id'] == 'ticket-1'
    assert result['unresolved_agents'] == ['web_search']
