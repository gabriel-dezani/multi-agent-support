"""Long-context, real SQLite, deterministic multi-turn regression without an LLM.

Scenarios are developer-authored contracts, not human-reviewed semantic results.
No external providers, API tokens or embeddings are loaded.
"""
import argparse
import json
import logging
import tempfile
from pathlib import Path

from app.agents.router import RouterAgent
from app.memory.store import ConversationMemoryStore
from app.orchestration.context import contextual_user_anchor
from app.orchestration.review_policy import bounded_replan, choose_next

log = logging.getLogger(__name__)


def evaluate() -> dict:
    failures = []
    checks = 0
    def check(label, actual, expected):
        nonlocal checks
        checks += 1
        if actual != expected:
            failures.append({'check': label, 'expected': expected, 'actual': actual})

    with tempfile.TemporaryDirectory(prefix='multi-turn-offline-') as temp:
        file = str(Path(temp) / 'memory.db')
        writer = ConversationMemoryStore(file)
        router = RouterAgent(enable_llm=False)
        for user, session, first, expected in (
            ('alice','session-a','Minhas vendas de ontem','customer_support'),
            ('bob','session-a','Como funciona o Pix?','knowledge'),
            ('alice','session-b','Como funciona o Pix?','knowledge'),
        ):
            writer.append_turn(session,user,first,'Resposta verificada', 'first')
            for index in range(140):
                utterance = ('E hoje?' if index % 2 else 'E quanto foi?') if expected == 'customer_support' else 'E isso?'
                writer.append_turn(session,user,utterance,'Continuidade',f'followup-{index}')
            # Simulate a second API process: completely new DB connection/store.
            recovered = ConversationMemoryStore(file)
            history = recovered.get_history(session,user,limit=12,current_message='E isso?')
            check(f'{user}/{session}/window_length', len(history), 12)
            check(f'{user}/{session}/anchor', contextual_user_anchor('E isso?',history), first)
            check(f'{user}/{session}/route', router.route('E isso?',user,history)['plan'],[expected])
        # A new explicit topic must not reuse a stale, unrelated support anchor.
        explicit_history = writer.get_history('session-a','alice',limit=12,
                                              current_message='Como funciona o Pix?')
        check('topic_change/anchor_absent', any('context_anchor' in row for row in explicit_history),False)
        check('topic_change/route',router.route('Como funciona o Pix?','alice',explicit_history)['plan'],['knowledge'])
        # A second store and a different user never see the same session history.
        check('ownership_unknown_user', writer.get_history('session-b','mallory'), [])
        check('ownership_unknown_session', writer.get_history('session-c','alice'), [])
        # Test the real supervisor with weak/factual evidence and strict budget.
        for idx in range(60):
            private = bool(idx % 2)
            state = {'message':'Minhas vendas Pix Getnet' if private else 'Explique Pix Getnet',
                     'plan':['knowledge'],'current_step':1,
                     'agent_results':[{'agent':'knowledge','confidence':0.1,
                                        'sources':[],'answer':'','requires_human':True}]}
            decision = bounded_replan(state,web_available=True,max_agents=3)
            check(f'supervisor/{idx}/replan', bool(decision), not private)
            next_node = choose_next({**state,**decision})
            check(f'supervisor/{idx}/next', next_node,'human_escalation' if private else 'web_search')
        check('session_count_after_restart',len(writer.get_history('session-a','alice',limit=500)),282)
    return {'status':'pass' if not failures else 'fail', 'checks':checks,
            'developer_authored':True, 'external_api_calls':0,'failures':failures}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='long_turn_scorecard.json')
    args=parser.parse_args()
    report=evaluate()
    Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    log.info('Long-turn offline contract: %s (%d checks; API calls: 0)',
             report['status'],report['checks'])
    if report['failures']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
