"""Check *real* FastAPI + SQLite contracts with a deliberately fake agent graph.

Usage: python -m scripts.offline_api_smoke
This does not execute LangGraph, Chroma, LLMs or network calls.
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path


def install_missing_library_stubs():
    try:
        import structlog  # noqa
    except ImportError:
        pkg = types.ModuleType('structlog')
        pkg.__path__ = []
        pkg.configure = lambda **kwargs: None
        methods = {name: lambda *a, **kw: None for name in ('info','warning','error','exception')}
        pkg.get_logger = lambda *a: types.SimpleNamespace(**methods)
        context = types.ModuleType('structlog.contextvars')
        context.bind_contextvars = lambda **kw: None
        context.clear_contextvars = lambda: None
        context.merge_contextvars = lambda *args: None
        processors = types.ModuleType('structlog.processors')
        processors.add_log_level = lambda *a: None
        processors.TimeStamper = lambda **kw: None
        processors.JSONRenderer = lambda **kw: None
        pkg.contextvars = context
        pkg.processors = processors
        sys.modules.update({'structlog':pkg,'structlog.contextvars':context,'structlog.processors':processors})

    from app.agents.human_escalation import HumanEscalationAgent
    class FakeGraph:
        async def ainvoke(self,state):
            if 'atendente' in state['message'].lower():
                result=HumanEscalationAgent().process('Pedido explícito','req-'+state['request_id'],
                    user_id=state['user_id'],conversation_id=state['conversation_id'],message=state['message'])
                return {**result,'route':'human_escalation','route_reason':'Atendente solicitado',
                        'agent':'human_escalation','agents_used':['human_escalation'],
                        'plan':['human_escalation'],'traces':[{'agent':'human_escalation','duration_ms':1,'status':'pending'}]}
            return {'route':'knowledge','route_reason':'Conhecimento','agent':'knowledge',
                    'answer':'Resposta simulada','confidence':0.8,'requires_human':False,
                    'agents_used':['knowledge'],'plan':['knowledge'],
                    'traces':[{'agent':'knowledge','duration_ms':1,'status':'ok'}]}
    fake = types.ModuleType('app.orchestration.graph')
    fake.build_graph = lambda: FakeGraph()
    sys.modules['app.orchestration.graph']=fake


def main():
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory() as directory:
        os.environ['STATE_DB_PATH'] = str(Path(directory)/'state.db')
        os.environ['API_CREDENTIALS_JSON']=json.dumps({
            'alice-token':{'user_id':'alice','role':'customer'},
            'bob-token':{'user_id':'bob','role':'customer'}})
        os.environ['OPERATOR_TOKEN']='operator-local-secret'
        install_missing_library_stubs()
        from app.core.config import get_settings
        get_settings.cache_clear()
        from app.main import app
        client=TestClient(app)
        alice={'Authorization':'Bearer alice-token'}
        bob={'Authorization':'Bearer bob-token'}
        op={'X-Operator-Token':'operator-local-secret'}
        count=0
        def check(value,reason):
            nonlocal count
            assert value,reason
            count+=1
        payload={'message':'Quero falar com atendente','user_id':'alice'}
        check(client.get('/health').status_code==200,'health')
        check(client.post('/chat',json=payload).status_code==401,'auth required')
        check(client.post('/chat',headers=bob,json=payload).status_code==403,'identity spoof denied')
        check(client.post('/chat',headers=alice,json={**payload,'role':'operator'}).status_code==422,'extra fields denied')
        first=client.post('/chat',headers=alice,json=payload)
        check(first.status_code==200,first.text)
        value=first.json();cid=value['conversation_id']; case=value['handoff_id']
        check(value['requires_human'] and bool(case),'ticket created')
        check(client.get('/handoffs').status_code==403,'operator denied without token')
        check(client.get('/handoffs',headers=op).json()['items'][0]['handoff_id']==case,'operator queue')
        check(client.get(f'/my-handoffs/{cid}',headers=bob).json()['items']==[],'other user cannot read tickets')
        check(client.get(f'/my-handoffs/{cid}',headers=alice).json()['items'][0]['status']=='pending','owner reads own case')
        again=client.post('/chat',headers=alice,json={'message':'Alguma novidade?','user_id':'alice','conversation_id':cid})
        check(again.status_code==200 and again.json()['handoff_id']==case,'waiting reuses case')
        check(len(client.get('/handoffs',headers=op).json()['items'])==1,'no duplicate ticket')
        check(client.post(f'/handoffs/{case}/resolve',json={'resolution':'done','resolved_by':'operator'}).status_code==403,'operator token required')
        resolved=client.post(f'/handoffs/{case}/resolve',headers=op,json={'resolution':'Orientação humana','resolved_by':'operator'})
        check(resolved.status_code==200 and resolved.json()['status']=='resolved','human resolved')
        check(resolved.json()['resolved_by']=='local-operator','operator audit identity is not user-supplied')
        twice=client.post(f'/handoffs/{case}/resolve',headers=op,json={'resolution':'should not write','resolved_by':'operator'})
        check(twice.status_code==200,'idempotent repeat')
        history=client.get(f'/conversations/{cid}',headers=op,params={'user_id':'alice'}).json()['messages']
        check(sum(x['role']=='human' for x in history)==1,'single human response in memory')
        check(history[-1]['content']=='Orientação humana','correct response stored')
        resumed=client.post('/chat',headers=alice,json={'message':'O que mais?','user_id':'alice','conversation_id':cid})
        check(resumed.status_code==200 and resumed.json()['agent']=='knowledge','session continues')
        check(client.get('/metrics').status_code==403,'metrics protected')
        metric=client.get('/metrics',headers=op).json()
        check(metric['requests']==3,'request count')
        trace=client.get('/traces/'+resumed.json()['request_id'],headers=op).json()
        check(trace['spans'][0]['agent']=='knowledge','persisted trace')
        check(client.post('/feedback',headers=bob,json={'request_id':resumed.json()['request_id'],'rating':5}).status_code==404,'feedback cannot be spoofed')
        check(client.post('/feedback',headers=alice,json={'request_id':resumed.json()['request_id'],'rating':5}).status_code==200,'owner feedback')
        check(client.get('/metrics',headers=op).json()['feedback_count']==1,'feedback aggregated')
        print(f'PASS: {count} HTTP API assertions (FastAPI + SQLite real, fake graph only).')

if __name__=='__main__':
    main()
