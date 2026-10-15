import math
import structlog
from contextvars import ContextVar

from app.core.config import get_settings
from app.rag.vector_store import get_vector_store

log = structlog.get_logger(__name__)
_recovered = ContextVar("rag_hnsw_recovered", default=False)


def normalized_relevance(rows):
    """Drop nonfinite relevance and clamp floating point precision spillover.

    Some Chroma distance conversions yield 1.00000002 for an exact match.
    Clamping ensures downstream consumers always receive [0, 1]. Do not
    pretend an implausible raw similarity (>1 by more than epsilon) is valid.
    """
    accepted = []
    for doc, value in rows:
        try:
            score = float(value)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(score) or score < -1e-6 or score > 1 + 1e-6:
            continue
        accepted.append((doc, max(0.0, min(1.0, score))))
    return accepted


class KnowledgeRetriever:
    def __init__(self, store=None):
        self.store = store or get_vector_store()
        self._metadata = ContextVar("rag_retrieval_metadata", default={})

    def retrieve(self, query, *, hybrid_enabled=None, mode=None):
        """Hybrid candidate ranking, with mandatory dense-relevance filtering.

        Independent sparse candidates are admitted by exact semantic relevance.
        Lexical/index failures fall back to dense, never to unverified BM25.
        """
        from time import monotonic
        from app.rag.ranking import document_key, hybrid_fuse
        from app.rag.lexical import lexical_candidates, exact_relevance

        if mode not in (None, 'dense', 'lexical', 'hybrid'):
            raise ValueError('unsupported retrieval mode')

        _recovered.set(False)
        self._metadata.set({})
        if not isinstance(query, str) or not query.strip():
            return []
        settings = get_settings()
        started = monotonic()
        mode = mode or ('hybrid' if (settings.rag_hybrid_enabled if hybrid_enabled is None
                                    else bool(hybrid_enabled)) else 'dense')
        k = settings.rag_top_k
        candidate_k = k if k > 20 else min(k * settings.rag_candidate_multiplier, 100)
        rows = []
        try:
            rows = ([] if mode == 'lexical' else
                    self.store.similarity_search_with_relevance_scores(query, k=candidate_k))
            # Chroma can silently underfill after HNSW delete/update cycles.
            active_count = self.store._collection.count()
            if mode != 'lexical' and len(rows) < min(candidate_k, active_count):
                rows = self._recover_hnsw(query, candidate_k)
        except RuntimeError as exc:
            if "Cannot return the results in a contig" not in str(exc):
                raise
            rows = self._recover_hnsw(query, candidate_k)

        bounded_rows = normalized_relevance(rows)
        accepted = [(doc, score) for doc, score in bounded_rows
                    if score >= settings.rag_min_relevance]
        self._metadata.set({"hnsw_recovered": _recovered.get(), "dense_candidates": len(bounded_rows),
                            "lexical_candidates": 0, "hybrid_used": False})
        if mode != 'dense':
            try:
                sparse, vectors = lexical_candidates(self.store, query,
                    max_chunks=settings.rag_lexical_max_chunks, limit=candidate_k)
                known = {document_key(doc) for doc, _ in bounded_rows}
                additional = normalized_relevance(exact_relevance(self.store, query,
                    [(doc, score) for doc, score in sparse if document_key(doc) not in known], vectors))
                # Never rescue a known below-threshold dense result by BM25.
                eligible = accepted + [(doc, score) for doc, score in additional
                                       if score >= settings.rag_min_relevance]
                eligible_by_key = {document_key(doc): (doc, score) for doc, score in eligible}
                safe_sparse = [eligible_by_key[document_key(doc)] for doc, _ in sparse
                               if document_key(doc) in eligible_by_key]
                accepted = hybrid_fuse(
                    accepted if mode == 'hybrid' else [], sparse, limit=k,
                    min_dense_relevance=settings.rag_min_relevance,
                    rrf_k=settings.rag_rerank_rrf_k,
                    max_per_source=settings.rag_max_chunks_per_source,
                    verified_lexical=safe_sparse,
                )
                self._metadata.set({"hnsw_recovered": _recovered.get(),
                                    "dense_candidates": len(bounded_rows),
                                    "lexical_candidates": len(sparse), "hybrid_used": mode == 'hybrid',
                                    "lexical_admitted": len(safe_sparse),
                                    "lexical_only_admitted": sum(score >= settings.rag_min_relevance for _, score in additional)})
            except (AttributeError, RuntimeError, ValueError, TypeError) as exc:
                log.warning("rag_lexical_fallback", error_type=type(exc).__name__)
                accepted = accepted[:k]
        else:
            accepted = accepted[:k]
        info = dict(self._metadata.get())
        info["retrieval_ms"] = round((monotonic() - started) * 1000, 2)
        self._metadata.set(info)
        return accepted

    def retrieval_metadata(self):
        return dict(self._metadata.get())

    def _recover_hnsw(self, query, k):
        """Recover a failed native query with a fresh HNSW over active Chroma vectors.

        Chroma 0.6.3 can fail after deletions with coincident vectors, including
        when active_count > k. Keep persisted data and relevance conversion;
        never lower k to conceal the failure or re-embed stored documents.
        Recovery failures propagate to KnowledgeAgent's normal abstention.
        """
        import hnswlib
        import numpy as np
        from langchain_core.documents import Document

        _recovered.set(True)
        data = self.store.get(include=["documents", "metadatas", "embeddings"])
        count = len(data["ids"])
        if not count:
            return []
        vectors = np.asarray(data["embeddings"], dtype=np.float32)
        metadata = self.store._collection.metadata or {}
        index = hnswlib.Index(space=metadata.get("hnsw:space", "l2"), dim=vectors.shape[1])
        index.init_index(
            max_elements=count,
            ef_construction=metadata.get("hnsw:construction_ef", 100),
            M=metadata.get("hnsw:M", 16),
        )
        index.add_items(vectors, np.arange(count), num_threads=1)
        index.set_ef(max(metadata.get("hnsw:search_ef", 100), k))
        query_vector = self.store.embeddings.embed_query(query)
        labels, distances = index.knn_query(
            np.asarray([query_vector], dtype=np.float32), k=min(k, count), num_threads=1
        )
        relevance = self.store._select_relevance_score_fn()
        log.warning("rag_hnsw_recovery", active_records=count, requested_top_k=k)
        return [
            (Document(page_content=data["documents"][int(label)],
                      metadata=data["metadatas"][int(label)] or {}), relevance(float(distance)))
            for label, distance in zip(labels[0], distances[0])
        ]
