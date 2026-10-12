import structlog
from contextvars import ContextVar

from app.core.config import get_settings
from app.rag.vector_store import get_vector_store

log = structlog.get_logger(__name__)
_recovered = ContextVar("rag_hnsw_recovered", default=False)


class KnowledgeRetriever:
    def __init__(self, store=None):
        self.store = store or get_vector_store()

    def retrieve(self, query):
        _recovered.set(False)
        settings = get_settings()
        try:
            rows = self.store.similarity_search_with_relevance_scores(
                query, k=settings.rag_top_k
            )
            # The persistent buffer/HNSW merge can also silently underfill.
            # Compare before threshold filtering, using the real active count.
            if (len(rows) < settings.rag_top_k and
                    len(rows) < min(settings.rag_top_k, self.store._collection.count())):
                rows = self._recover_hnsw(query, settings.rag_top_k)
        except RuntimeError as exc:
            if "Cannot return the results in a contig" not in str(exc):
                raise
            rows = self._recover_hnsw(query, settings.rag_top_k)
        return [(doc, score) for doc, score in rows if score >= settings.rag_min_relevance]

    def retrieval_metadata(self):
        return {"hnsw_recovered": _recovered.get()}

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
