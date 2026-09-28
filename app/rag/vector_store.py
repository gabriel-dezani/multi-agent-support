from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from app.core.config import get_settings
def get_vector_store():
 s=get_settings(); e=OpenAIEmbeddings(model=s.embedding_model,api_key=s.openai_api_key)
 return Chroma(collection_name=s.rag_collection,persist_directory=s.vector_store_path,embedding_function=e)
