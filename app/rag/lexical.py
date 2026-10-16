"""Independent BM25 candidates with exact, fail-closed semantic admission.

BM25 scores are never converted into confidence. A lexical-only hit must pass
the same Chroma relevance conversion and floor as an ANN candidate. Stored
embeddings are reused; documents are never re-embedded for this check.
"""
import math

from langchain_core.documents import Document

from app.rag.ingestion import _valid_url
from app.rag.ranking import bm25_rank, document_key


def lexical_candidates(store, query, *, max_chunks, limit):
    snapshot = store.get(include=['documents', 'metadatas', 'embeddings'], limit=max_chunks)
    documents, vectors = [], {}
    embeddings = snapshot.get('embeddings')
    contents = snapshot.get('documents') or []
    metadata = snapshot.get('metadatas') or []
    for index, (content, meta) in enumerate(zip(contents, metadata)):
        if not content or not _valid_url((meta or {}).get('source_url', '')):
            continue
        doc = Document(page_content=content, metadata=meta or {})
        documents.append(doc)
        if embeddings is not None and index < len(embeddings):
            vectors[document_key(doc)] = embeddings[index]
    return bm25_rank(query, documents)[:limit], vectors


def exact_relevance(store, query, candidates, vectors):
    """Score candidates omitted by ANN using its metric, not lexical overlap."""
    if not candidates:
        return []
    query_vector = list(store.embeddings.embed_query(query))
    if not query_vector or not all(math.isfinite(float(v)) for v in query_vector):
        raise ValueError('invalid query embedding')
    metric = (store._collection.metadata or {}).get('hnsw:space', 'l2')
    convert = store._select_relevance_score_fn()
    results = []
    for doc, _ in candidates:
        vector = vectors.get(document_key(doc))
        if vector is None or len(vector) != len(query_vector):
            continue
        vector = [float(v) for v in vector]
        if not all(math.isfinite(v) for v in vector):
            continue
        if metric == 'l2':
            distance = sum((float(a)-b)**2 for a, b in zip(query_vector, vector))
        else:
            dot = sum(float(a)*b for a, b in zip(query_vector, vector))
            if metric == 'cosine':
                norm = math.sqrt(sum(float(a)**2 for a in query_vector) * sum(b*b for b in vector))
                if not norm:
                    continue
                distance = 1 - dot/norm
            elif metric == 'ip':
                distance = 1 - dot
            else:
                raise ValueError('unsupported vector metric')
        results.append((doc, convert(distance)))
    return results
