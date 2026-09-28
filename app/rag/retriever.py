from app.core.config import get_settings
from app.rag.vector_store import get_vector_store
class KnowledgeRetriever:
 def __init__(self,store=None): self.store=store or get_vector_store()
 def retrieve(self,query):
  s=get_settings(); return [(d,score) for d,score in self.store.similarity_search_with_relevance_scores(query,k=s.rag_top_k) if score>=s.rag_min_relevance]
