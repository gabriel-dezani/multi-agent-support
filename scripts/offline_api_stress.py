"""Concurrent HTTP stress of real FastAPI/SQLite, with simulated graph only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import logging
import os
import tempfile
import sqlite3

from scripts.offline_api_smoke import install_missing_library_stubs


def main():
    from fastapi.testclient import TestClient
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as td:
        os.environ['STATE_DB_PATH']=str(Path(td)/'state.db')
        os.environ['API_CREDENTIALS_JSON']=json.dumps({
            'alice':{'user_id':'alice','role':'customer'},
            'bob':{'user_id':'bob','role':'customer'},
            'operator-bearer':{'user_id':'verified-operator','role':'operator'},
        })
        os.environ['OPERATOR_TOKEN']='local-secret'
        install_missing_library_stubs()
        from app.core.config import get_settings
        get_settings.cache_clear()
        from app.main import app
        import app.api.routes as routes
        client=TestClient(app)
        a={'Authorization':'Bearer alice'}
        b={'Authorization':'Bearer bob'}
        op={'Authorization':'Bearer operator-bearer'}

        def chat(n):
            return client.post('/chat',headers=a,json={
                'message':f'Quero falar com atendente, evento {n}',
                'user_id':'alice', 'conversation_id':'busy-alice-session',
            })
        with ThreadPoolExecutor(max_workers=12) as pool:
            results=list(pool.map(chat,range(60)))
        assert all(response.status_code==200 for response in results),[
            (response.status_code,response.text) for response in results if response.status_code!=200
        ]
        tickets={response.json()['handoff_id'] for response in results}
        assert len(tickets)==1 and None not in tickets, tickets
        case=tickets.pop()
        assert len(client.get('/handoffs',headers=op).json()['items'])==1
        assert client.get('/handoffs',headers=a).status_code==403
        assert client.get('/my-handoffs/busy-alice-session',headers=b).json()['items']==[]

        def resolve(n):
            return client.post(f'/handoffs/{case}/resolve',headers=op,json={
                'resolution':f'verified answer {n}', 'resolved_by':'SPOOFED-ADMIN',
            })
        with ThreadPoolExecutor(max_workers=12) as pool:
            resolved=list(pool.map(resolve,range(40)))
        assert all(response.status_code==200 for response in resolved)
        assert {response.json()['status'] for response in resolved}=={'resolved'}
        record=client.get(f'/handoffs/{case}',headers=op).json()
        assert record['resolved_by']=='verified-operator',record
        history=client.get('/conversations/busy-alice-session',headers=op,
                           params={'user_id':'alice'}).json()['messages']
        assert sum(row['role']=='human' for row in history)==1
        assert len(history)<=get_settings().memory_max_messages
        with sqlite3.connect(os.environ['STATE_DB_PATH']) as db:
            counts=dict(db.execute("SELECT role,COUNT(*) FROM conversation_messages WHERE conversation_id='busy-alice-session' AND user_id='alice' GROUP BY role").fetchall())
        assert counts=={'user':60,'assistant':60,'human':1},counts
        assert client.post('/chat',headers=b,json={'message':'My sales',
               'user_id':'alice','conversation_id':'busy-alice-session'}).status_code==403
        for n in range(10):
            response=client.post('/chat',headers=b,json={'message':'demo knowledge question',
                'user_id':'bob','conversation_id':f'bob-{n}'})
            assert response.status_code==200
        assert len(client.get('/conversations/busy-alice-session',headers=op,
                              params={'user_id':'bob'}).json()['messages'])==0
        metric=client.get('/metrics',headers=op).json()
        assert metric['requests']>=70
        print('PASS: 60 parallel HTTP handoffs -> one ticket; 40 parallel operator resolutions -> '
              'one audited human reply; 10 other-user requests; tenant isolation and metrics.')


if __name__=='__main__':
    main()
