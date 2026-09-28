from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    tavily_api_key: str = ""
    vector_store_path: str = ".vector_data"
    rag_collection: str = "getnet_products"
    rag_top_k: int = Field(default=4, ge=1, le=20)
    rag_min_relevance: float = Field(default=0.45, ge=0.0, le=1.0)
    request_timeout_seconds: float = Field(default=15, gt=0, le=120)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings():
    return Settings()
