from app.memory.store import ConversationMemoryStore
from app.agents.router import RouterAgent
from app.orchestration.context import contextual_user_anchor
from scripts.offline_long_turn_scorecard import evaluate


def test_real_sqlite_134_long_turn_isolation_checks():
    report = evaluate()
    assert report['status'] == 'pass'
    assert report['checks'] >= 130
    assert not report['failures']
    assert report['external_api_calls'] == 0


def test_new_explicit_topic_does_not_resurrect_an_old_anchor(tmp_path):
    store = ConversationMemoryStore(str(tmp_path/'t.db'))
    store.append_turn('session','alice','Minhas vendas de ontem','ok','old')
    for n in range(40):
        store.append_turn('session','alice','E hoje?','ok',str(n))
    history = store.get_history('session','alice',current_message='Como funciona o Pix?')
    assert not any('context_anchor' in row for row in history)
    assert RouterAgent(enable_llm=False).route('Como funciona o Pix?','alice',history)['plan'] == ['knowledge']
    followup = store.get_history('session','alice',current_message='E isso?')
    assert contextual_user_anchor('E isso?',followup) == 'Minhas vendas de ontem'


def test_cross_user_same_conversation_never_inherits_private_anchor(tmp_path):
    store = ConversationMemoryStore(str(tmp_path/'s.db'))
    store.append_turn('shared','alice','Minhas vendas de ontem','private','alice-1')
    store.append_turn('shared','bob','Como funciona o Pix?','public','bob-1')
    for idx in range(18):
        store.append_turn('shared','alice','E hoje?','private',str(idx))
        store.append_turn('shared','bob','E isso?','public',str(idx))
    bob = store.get_history('shared','bob',limit=6,current_message='E isso?')
    assert contextual_user_anchor('E isso?',bob) == 'Como funciona o Pix?'
    assert 'vendas' not in repr(bob).lower()
