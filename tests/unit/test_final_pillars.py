"""Final engineering regressions: storage is local, providers are never called."""
import asyncio
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from app.core.distributed_lock import postgres_conversation_lock
from app.memory.store import ConversationMemoryStore
from app.orchestration.context import contextual_user_anchor
from app.orchestration.review_policy import bounded_replan
from app.rag.retriever import KnowledgeRetriever
from scripts.offline_final_pillars import retrieval_benchmark, memory_benchmark


def test_three_mode_retrieval_real_chroma_gains_and_preserves_complementarity():
    report = retrieval_benchmark()
    modes = report['modes']
    assert modes['dense']['scores']['recall_at_k'] == .6667
    assert modes['lexical']['scores']['recall_at_k'] == .6667
    assert modes['previous_rerank']['scores']['recall_at_k'] == .6667
    assert all(score == 1 for score in modes['hybrid']['scores'].values())
    assert report['human_reviewed'] is False


@pytest.mark.parametrize('size',[250,500,1000])
def test_indexed_memory_outlives_old_scan_limit(size):
    [report] = memory_benchmark((size,))
    assert report['before_anchor_recovered'] is False
    assert report['after_anchor_recovered'] is True
    assert report['topic_index_used'] is True
    assert report['named_old_topic_recovered'] is True


def test_additive_topic_migration_and_retention_do_not_leave_anchors(tmp_path):
    path = str(tmp_path/'legacy.db')
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE conversation_messages(id INTEGER PRIMARY KEY,conversation_id TEXT,user_id TEXT,'
                   'role TEXT,content TEXT,request_id TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute("INSERT INTO conversation_messages VALUES(1,'c','alice','user','Minhas vendas ALFA','old','2000-01-01')")
        db.executemany("INSERT INTO conversation_messages(conversation_id,user_id,role,content,request_id) "
                       "VALUES('c','alice','user','E hoje?',?)",[(str(i),) for i in range(1000)])
        db.commit()
    migrated = ConversationMemoryStore(path)
    assert contextual_user_anchor('E isso?',migrated.get_history('c','alice',current_message='E isso?')) == 'Minhas vendas ALFA'
    assert migrated.purge_expired(1) == 1
    assert contextual_user_anchor('E isso?',migrated.get_history('c','alice',current_message='E isso?')) == ''
    migrated.append_turn('c','alice','Como funciona o Pix?','ok','new')
    migrated.clear('c','alice')
    assert migrated.get_history('c','alice',current_message='Retome o assunto vendas') == []
    assert ConversationMemoryStore(path).get_history('c','alice') == []


def test_simultaneous_long_sessions_and_failed_turn_resume(tmp_path):
    path = str(tmp_path/'parallel.db')
    ConversationMemoryStore(path)
    def write(owner):
        store = ConversationMemoryStore(path)
        store.append_turn('shared',owner,f'Minhas vendas {owner}','ok','start')
        for index in range(250):
            store.append_turn('shared',owner,'E hoje?','ok',str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write,['alice','bob']))
    store = ConversationMemoryStore(path)
    for owner in ['alice','bob']:
        history = store.get_history('shared',owner,current_message='E isso?')
        assert contextual_user_anchor('E isso?',history) == f'Minhas vendas {owner}'
    with pytest.raises(sqlite3.IntegrityError):
        store.append_turn('shared','alice','Como funciona Link?',None,'failed')
    assert contextual_user_anchor('E isso?',store.get_history('shared','alice',current_message='E isso?')) == 'Minhas vendas alice'
    ConversationMemoryStore(path).append_turn('shared','alice','Como funciona Link?','ok','failed')
    assert contextual_user_anchor('E isso?',store.get_history('shared','alice',current_message='E isso?')) == 'Como funciona Link?'


def test_replan_checks_policy_errors_and_specialist_availability():
    state = dict(message='Explique Pix Getnet',plan=['web_search'],current_step=1,
                 agent_results=[dict(agent='web_search',answer='',sources=[],confidence=0,
                                     requires_human=True,provider_unavailable=True)])
    assert bounded_replan(state,web_available=False)['plan'] == ['web_search','knowledge']
    assert bounded_replan(state,web_available=False,knowledge_available=False) == {}
    state['agent_results'][0]['errors'] = ['web_search:privacy_blocked']
    assert bounded_replan(state,web_available=False) == {}


def test_named_topic_remains_available_after_resume_is_persisted(tmp_path):
    store = ConversationMemoryStore(str(tmp_path/'resume.db'))
    store.append_turn('c','alice','Minhas vendas do pedido ALFA','ok','first')
    store.append_turn('c','alice','Como funciona o Pix?','ok','new')
    store.append_turn('c','alice','Retome o assunto vendas','ok','resume')
    assert contextual_user_anchor('E isso?',store.get_history('c','alice',current_message='E isso?')) == 'Minhas vendas do pedido ALFA'
    for index in range(8):
        store.append_turn('c','alice','E hoje?','ok',str(index))
    restarted = ConversationMemoryStore(str(tmp_path/'resume.db'))
    history = restarted.get_history('c','alice',current_message='E isso?')
    assert contextual_user_anchor('E isso?',history) == 'Minhas vendas do pedido ALFA'


@pytest.mark.parametrize('outage', ['unavailable','timeout'])
def test_real_graph_can_replan_public_getnet_outage_to_local_rag(monkeypatch,outage):
    import app.orchestration.graph as module
    from app.core.upstream import UpstreamUnavailable
    calls = []
    class Web:
        async def process(self,*args,**kwargs):
            calls.append('web')
            if outage == 'timeout':
                await asyncio.sleep(.1)
            raise UpstreamUnavailable('synthetic outage')
    def know(*args,**kwargs):
        calls.append('knowledge')
        return dict(answer='Pix verificado',sources=['https://site.getnet.com.br/pix/'],
                    confidence=.9,requires_human=False)
    monkeypatch.setattr(module,'get_settings',lambda:SimpleNamespace(
        router_max_agents=3,request_timeout_seconds=.01,tavily_api_key=''))
    router = SimpleNamespace(route=lambda *args:dict(route='web_search',plan=['web_search']))
    graph = module.build_graph(router=router,knowledge=SimpleNamespace(process=know),
        support=object(),web=Web(),escalation=object())
    result = asyncio.run(graph.ainvoke(dict(message='Explique Pix Getnet',user_id='alice',
        request_id='r',conversation_id='c',history=[])))
    assert calls == ['web','knowledge']
    assert result['plan'] == ['web_search','knowledge']
    assert result['answer'] == 'Pix verificado'
    assert result['requires_human'] is False
    assert result['rag_getnet_recovery'] is True
    assert 'web_search:provider_unavailable' in result['errors']


@pytest.mark.parametrize('tables,readonly,expected', [
    (['conversation_messages','handoffs','request_stats'],False,False),
    (['conversation_messages','handoffs','request_stats','request_spans','user_feedback'],False,True),
    (['conversation_messages','handoffs','request_stats','request_spans','user_feedback'],True,False),
])
def test_postgres_readiness_requires_complete_state_and_writable_session(monkeypatch,tmp_path,tables,readonly,expected):
    import app.core.postgres_state as pg
    from app.core.readiness import check_readiness
    class Session:
        def execute(self,sql):
            return SimpleNamespace(fetchall=lambda:[(name,) for name in tables],
                                   fetchone=lambda:('on' if readonly else 'off',))
    @contextmanager
    def session(_):
        yield Session()
    monkeypatch.setattr(pg,'pg_session',session)
    assert check_readiness(SimpleNamespace(state_backend='postgres',vector_store_path=str(tmp_path),
                                           state_database_url='unused')) is expected


class LexicalStore:
    def __init__(self, *, url='https://site.getnet.com.br/pix/',vector=(1.,0.), dense=()):
        self.document = Document(page_content='cobalt42 pagamentos',metadata={'source_url':url,'chunk_id':'lex'})
        self.vector = vector
        self.dense = dense
        self._collection = SimpleNamespace(count=lambda:0,metadata={'hnsw:space':'cosine'})
        self.embeddings = SimpleNamespace(embed_query=lambda q:[1.,0.])
    def similarity_search_with_relevance_scores(self,*args,**kwargs):
        return self.dense
    def get(self,**kwargs):
        return dict(documents=[self.document.page_content],metadatas=[self.document.metadata],embeddings=[self.vector])
    def _select_relevance_score_fn(self):
        return lambda distance:1-distance


def test_lexical_operates_when_dense_returns_no_candidates():
    retriever = KnowledgeRetriever(LexicalStore())
    assert retriever.retrieve('cobalt42',mode='dense') == []
    assert len(retriever.retrieve('cobalt42',mode='hybrid')) == 1
    assert retriever.retrieval_metadata()['lexical_only_admitted'] == 1


@pytest.mark.parametrize('options',[
    dict(url='https://evil.example/pix/'),dict(vector=(0.,1.)),dict(vector=(float('nan'),0.)),
    dict(vector=None),dict(vector=(1.,)),dict(url='https://site.getnet.com.br:bad/pix/'),
])
def test_raw_bm25_cannot_bypass_source_vector_or_relevance_gates(options):
    assert KnowledgeRetriever(LexicalStore(**options)).retrieve('cobalt42',mode='hybrid') == []


def test_known_low_dense_score_is_not_replaced_by_lexical_score():
    store = LexicalStore()
    store.dense = [(store.document,.1)]
    assert KnowledgeRetriever(store).retrieve('cobalt42',mode='hybrid') == []


@pytest.mark.parametrize('metric', ['cosine','l2','ip'])
def test_exact_admission_uses_same_chroma_metric(metric):
    from app.rag.lexical import exact_relevance
    store = LexicalStore(vector=(.8,.6))
    store._collection.metadata['hnsw:space'] = metric
    [(doc,score)] = exact_relevance(store,'q',[(store.document,99)],{'lex':store.vector})
    expected = {'cosine':.8,'l2':.6,'ip':.8}[metric]
    assert score == pytest.approx(expected)


def test_missing_lexical_snapshot_preserves_dense_and_reports_fallback():
    store = LexicalStore()
    store.dense = [(store.document,.9)]
    def broken(**kwargs):
        raise RuntimeError('snapshot unavailable')
    store.get = broken
    retriever = KnowledgeRetriever(store)
    assert retriever.retrieve('cobalt42') == store.dense
    assert retriever.retrieval_metadata()['hybrid_used'] is False


def test_lock_deadline_includes_slow_connect(monkeypatch):
    class Driver:
        @staticmethod
        async def connect(*args,**kwargs):
            await asyncio.sleep(10)
    monkeypatch.setitem(sys.modules,'psycopg',SimpleNamespace(AsyncConnection=Driver))
    async def run():
        with pytest.raises(TimeoutError):
            async with postgres_conversation_lock('unused','u','c',timeout=.02):
                pytest.fail('slow connect entered body')
    asyncio.run(run())


@pytest.mark.parametrize('advisory',[True,False])
def test_postgres_safety_timeouts_preserve_existing_connection_options(advisory):
    from app.core.postgres_state import connection_options
    options = connection_options('postgresql://localhost/test?options=-c%20search_path%3Dtenant%20-c%20statement_timeout%3D0',
                                 advisory=advisory)
    assert options.startswith('-c search_path=tenant -c statement_timeout=0 ')
    assert options.endswith('-c lock_timeout=5000') if advisory else 'idle_in_transaction_session_timeout=15000' in options
    assert options.rfind('statement_timeout=0') < options.rfind('statement_timeout=')


@pytest.mark.parametrize('fail_body',[True,False])
def test_lock_release_and_close_on_success_or_body_failure(monkeypatch,fail_body):
    calls = []
    class Connection:
        async def execute(self,sql,params):
            calls.append(sql)
            async def fetchone():
                return (True,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self):
            calls.append('closed')
    class Driver:
        @staticmethod
        async def connect(*args,**kwargs):
            assert 'statement_timeout' in kwargs['options']
            return Connection()
    monkeypatch.setitem(sys.modules,'psycopg',SimpleNamespace(AsyncConnection=Driver))
    async def run():
        try:
            async with postgres_conversation_lock('unused','u','c',timeout=.1):
                if fail_body:
                    raise RuntimeError('tool failed')
        except RuntimeError:
            assert fail_body
    asyncio.run(run())
    assert calls[-1] == 'closed'
    assert any('pg_advisory_unlock' in sql for sql in calls)
