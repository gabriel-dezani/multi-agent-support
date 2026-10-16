"""Real local Chroma/SQLite, fixed synthetic embeddings/labels, no API calls."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import tempfile
from time import perf_counter
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
from chromadb.config import Settings as ChromaSettings

from app.core.config import Settings
from app.evaluation.retrieval import compare_retrievers
from app.memory.store import ConversationMemoryStore
from app.orchestration.context import contextual_user_anchor
from app.rag.ranking import hybrid_fuse, bm25_rank
from app.rag.retriever import KnowledgeRetriever


class FixedEmbeddings(Embeddings):
    def __init__(self, vectors):
        self.vectors = vectors
    def embed_query(self, text):
        return self.vectors[text]
    def embed_documents(self, texts):
        return [self.vectors[text] for text in texts]


def retrieval_benchmark():
    docs, vectors, items = [], {}, []
    for index in range(12):
        query = f'code{index:02d} specification'
        vector = [0.0]*13
        vector[index] = 1.0
        vectors[query] = vector
        # Four dense misses (higher-similarity distractor), four lexical misses
        # (paraphrase with zero token overlap), four complementary agreements.
        category = ('ann_miss','paraphrase','agreement')[index//4]
        text = f'code{index:02d} specification verified' if category != 'paraphrase' else f'remote payment variant{index}'
        url = f'https://site.getnet.com.br/fixture/{index}'
        gold_vector = list(vector)
        if category == 'ann_miss':
            gold_vector[index], gold_vector[12] = .9, .435889894
            for number in range(13):
                decoy = f'unrelated device variant{index} copy{number}'
                vectors[decoy] = vector
                docs.append(Document(page_content=decoy,metadata={
                    'source_url':url+f'/decoy/{number}','chunk_id':f'd{index}-{number}'}))
        vectors[text] = gold_vector
        docs.append(Document(page_content=text,metadata={'source_url':url,'chunk_id':f'g{index}'}))
        items.append(dict(id=f'case-{index}',question=query,category=category,gold_source_urls=[url]))
    with tempfile.TemporaryDirectory(prefix='final-rag-') as directory:
        store = Chroma(collection_name='final_benchmark',persist_directory=directory,
            embedding_function=FixedEmbeddings(vectors),
            collection_metadata={'hnsw:space':'cosine'},
            client_settings=ChromaSettings(anonymized_telemetry=False))
        try:
            store.add_documents(docs,ids=[doc.metadata['chunk_id'] for doc in docs])
            settings = Settings(_env_file=None,rag_top_k=1,rag_candidate_multiplier=1)
            retriever = KnowledgeRetriever(store)
            with patch('app.rag.retriever.get_settings',return_value=settings):
                def before(query):
                    dense = retriever.retrieve(query,mode='dense')
                    return hybrid_fuse(dense,bm25_rank(query,docs),limit=1,min_dense_relevance=.45)
                report = compare_retrievers(items,{
                    'previous_rerank':before,
                    **{mode:(lambda q, m=mode:retriever.retrieve(q,mode=m))
                       for mode in ('dense','lexical','hybrid')}},k=1)
                settings.rag_top_k, settings.rag_candidate_multiplier = 4, 3
                at_four = compare_retrievers(items,{
                    mode:(lambda q, m=mode:retriever.retrieve(q,mode=m))
                    for mode in ('dense','lexical','hybrid')},k=4)
                report['at_k4_default_candidate_budget'] = at_four
            report['dataset_sha256'] = hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()
            report['categories'] = {category:sum(item['category']==category for item in items)
                                    for category in ('ann_miss','paraphrase','agreement')}
            report['limitation'] = ('Controlled fixed embeddings demonstrate candidate recall, not general semantic accuracy; '
                                   'lexical-only candidates still require exact semantic relevance >=0.45')
            return report
        finally:
            store._client._system.stop()


def memory_benchmark(sizes=(250,500,1000)):
    results = []
    for size in sizes:
        with tempfile.TemporaryDirectory(prefix='final-memory-') as directory:
            path = str(Path(directory)/'state.db')
            store = ConversationMemoryStore(path)
            topic = 'Minhas vendas de ontem do pedido ALFA'
            store.append_turn('shared','alice',topic,'ok','initial')
            started = perf_counter()
            for index in range(size):
                store.append_turn('shared','alice','E hoje?','ok',str(index))
            write_ms = (perf_counter()-started)*1000
            store.append_turn('shared','bob','Como funciona o Pix?','ok','initial')
            store.append_turn('other','alice','Como funciona o Link?','ok','initial')
            restarted = ConversationMemoryStore(path)
            timings = []
            for _ in range(10):
                started = perf_counter()
                history = restarted.get_history('shared','alice',limit=12,current_message='E isso?')
                timings.append((perf_counter()-started)*1000)
            with closing(sqlite3.connect(path)) as db:
                previous = db.execute("SELECT content FROM conversation_messages WHERE conversation_id='shared' "
                                      "AND user_id='alice' AND role='user' AND id<? ORDER BY id DESC LIMIT 200",
                                      (size*2-9,)).fetchall()
                legacy = contextual_user_anchor('E isso?', [{'role':'user','content':row[0]} for row in reversed(previous)])
                plan = [row[3] for row in db.execute("EXPLAIN QUERY PLAN SELECT topic_anchor FROM conversation_messages "
                    "WHERE conversation_id=? AND user_id=? AND id<? AND topic_anchor IS NOT NULL ORDER BY id DESC LIMIT 1",
                    ('shared','alice',size*2))]
            assert contextual_user_anchor('E isso?',history) == topic
            assert len(history) == 12
            assert restarted.get_history('shared','mallory',current_message='E isso?') == []
            assert 'ALFA' not in repr(restarted.get_history('shared','bob',current_message='E isso?'))
            assert 'ALFA' not in repr(restarted.get_history('other','alice',current_message='E isso?'))
            store.append_turn('shared','alice','Como funciona o Pix?','ok','changed')
            assert contextual_user_anchor('E isso?',store.get_history('shared','alice',current_message='E isso?')) == 'Como funciona o Pix?'
            recalled = store.get_history('shared','alice',current_message='Retome o assunto vendas')
            assert contextual_user_anchor('Retome o assunto vendas',recalled) == topic
            store.append_turn('shared','alice','Retome o assunto vendas','ok','resume')
            for index in range(8):
                store.append_turn('shared','alice','E hoje?','ok',f'resumed-{index}')
            assert contextual_user_anchor('E isso?',store.get_history('shared','alice',current_message='E isso?')) == topic
            assert not any('context_anchor' in row for row in store.get_history(
                'shared','alice',current_message='Como funciona o Link?'))
            results.append(dict(followup_turns=size,total_turns=size+1,
                before_anchor_recovered=legacy==topic,after_anchor_recovered=True,
                named_old_topic_recovered=True,resumed_topic_persisted=True,window_messages=12,isolation=True,restart=True,
                write_ms=round(write_ms,2),read_median_ms=round(statistics.median(timings),3),
                topic_index_used=any('idx_memory_topics' in step for step in plan)))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',default='docs/final_pillars_benchmark.json')
    args = parser.parse_args()
    report = dict(external_api_calls=0,human_reviewed=False,
                  retrieval=retrieval_benchmark(),memory=memory_benchmark())
    Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(external_api_calls=0, human_reviewed=False,
        retrieval={mode:result['scores'] for mode,result in report['retrieval']['modes'].items()},
        retrieval_k4={mode:result['scores'] for mode,result in
                      report['retrieval']['at_k4_default_candidate_budget']['modes'].items()},
        memory=report['memory']),ensure_ascii=False))
    assert all(row['topic_index_used'] for row in report['memory'])
    assert report['retrieval']['modes']['hybrid']['scores']['recall_at_k'] == 1


if __name__ == '__main__':
    main()
