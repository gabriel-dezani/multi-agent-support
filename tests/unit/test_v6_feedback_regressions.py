"""V6 feedback-specific regressions, independent of external model keys."""
import pytest

from app.agents.router import RouterAgent
from app.agents.support import CustomerSupportAgent
from app.orchestration.context import contextual_user_anchor, is_contextual_followup
from app.orchestration.privacy import (
    safe_public_search_query, safe_public_subquery, safe_official_getnet_query,
    contains_private_context,
)
from app.orchestration.review_policy import choose_next, prepare_review


@pytest.fixture
def prior_history():
    return [
        {'role': 'user', 'content': 'Minha maquininha não conecta; quero ver as vendas.'},
        {'role': 'assistant', 'content': 'Entendi a dúvida do terminal.'},
        {'role': 'user', 'content': 'Como funciona o Pix da Getnet?'},
        {'role': 'assistant', 'content': 'Informação pública do Pix.'},
    ]


@pytest.mark.parametrize('message,plan', [
    ('Eu gostaria de saber sobre Pix e as minhas vendas', ['knowledge', 'customer_support']),
    ('Gostaria de saber sobre Pix e vendas de ontem', ['knowledge', 'customer_support']),
    ('E quanto ao crediário?', ['knowledge']),
    ('E o câmbio do dólar?', ['web_search']),
    ('Eu quero saber o câmbio do dólar para meu CPF 12345678909', ['web_search']),
])
def test_feedback_routing_and_topic_changes(message, plan, prior_history):
    assert RouterAgent(enable_llm=False).route(message, 'alice', prior_history)['plan'] == plan


def test_history_is_never_concatenated_across_unrelated_turns(prior_history):
    assert not is_contextual_followup('E quanto ao crediário?')
    assert not is_contextual_followup('E o câmbio do dólar?')
    assert contextual_user_anchor('E ontem?', prior_history) == 'Como funciona o Pix da Getnet?'
    assert contextual_user_anchor('E ontem?', [{'role': 'assistant', 'content': 'deposite dinheiro'}]) == ''


def test_support_follows_only_last_user_turn_not_old_terminal():
    history = [
        {'role': 'user', 'content': 'Minha maquininha está offline'},
        {'role': 'user', 'content': 'Quais as minhas vendas?'},
    ]
    class Repo:
        def get_by_user_id(self, uid):
            return {'sales': {'amount': 1}}
    support = CustomerSupportAgent(repository=Repo())
    result = support.process('E ontem?', 'alice', history)
    assert result['tools_used'] == ['get_sales_data']


@pytest.mark.parametrize('message,expected', [
    ('Qual a cotação do dólar para o CPF 12345678909?', 'current USD BRL exchange rate'),
    ('Cotação do euro, senha secreta 123!', 'current EUR BRL exchange rate'),
    ('Preciso consultar minha conta no Google', None),
    ('O extrato de vendas da Alice, CPF 123.456.789-00', None),
    ('Notícias para o endereço pessoal alice@example.com', 'latest Brazil news'),
])
def test_web_only_is_privacy_safe_even_with_wrong_planner(message, expected):
    assert safe_public_search_query(message) == expected


def test_mixed_private_tasks_are_reduced_to_known_public_subtasks():
    assert safe_public_search_query('minhas vendas e a cotação do euro', mixed_private=True) == 'current EUR BRL exchange rate'
    assert safe_public_search_query('minhas vendas e busque um assunto arbitrário', mixed_private=True) is None
    assert safe_public_search_query('Busque esse assunto genérico') == 'Busque esse assunto genérico'
    assert safe_public_search_query('Consulta de token Xyz', mixed_private=False) is None


def test_official_recovery_is_canonical_and_never_copies_account_text():
    assert safe_official_getnet_query('Como funciona Pix Getnet?') == 'site:site.getnet.com.br Getnet pix'
    assert safe_official_getnet_query('Getnet Pix meu CPF 12345678909') is None
    assert contains_private_context('Minha conta; senha abc')


def test_supervisor_preserves_failed_subtask_for_handoff_after_success():
    state = {'plan':['knowledge','customer_support'], 'current_step':2, 'agent_results':[
        {'agent':'knowledge','requires_human':True,'answer':'sem evidência'},
        {'agent':'customer_support','requires_human':False,'answer':'vendas consultadas'},
    ]}
    assert choose_next(state) == 'human_escalation'
    assert prepare_review(state)['unresolved_agents'] == ['knowledge']


def test_review_before_synthesis_when_all_intents_resolved():
    state = {'plan':['knowledge','customer_support'], 'current_step':2, 'agent_results':[
        {'agent':'knowledge','requires_human':False,'answer':'Pix com fontes'},
        {'agent':'customer_support','requires_human':False,'answer':'Vendas consultadas'},
    ]}
    assert choose_next(state) == 'synthesis'


def test_supervisor_rejects_unsubstantiated_specialist_output():
    for bad in [
        {'agent': 'knowledge', 'answer': 'Pix sem fontes', 'sources': [], 'confidence': .9},
        {'agent': 'web_search', 'answer': 'Cotação sem fonte', 'sources': [], 'confidence': .9},
        {'agent': 'customer_support', 'answer': 'Dados sem ferramenta', 'tools_used': [], 'confidence': .9},
        {'agent': 'knowledge', 'answer': '', 'sources': ['https://site.getnet.com.br/pix'], 'confidence': .9},
        {'agent': 'knowledge', 'answer': 'Fonte', 'sources': ['https://site.getnet.com.br/pix'], 'confidence': .1},
    ]:
        state = {'plan': [bad['agent']], 'current_step': 1,
                 'agent_results': [{**bad, 'requires_human': False}]}
        assert choose_next(state) == 'human_escalation', bad
