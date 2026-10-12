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
    total_request_timeout_seconds: float = Field(default=90, gt=0, le=600)

    # Agentic routing: use an LLM structured classifier when a key is available,
    # with a deterministic fallback for resilience and offline tests.
    router_use_llm: bool = True
    router_max_agents: int = Field(default=3, ge=1, le=4)

    # Durable local state for multi-turn memory and human-handoff queue.
    state_db_path: str = ".state/support.db"
    memory_max_messages: int = Field(default=12, ge=2, le=50)

    # Operator endpoints are protected by an explicit token. Leave blank to
    # disable operator actions until a secret is configured.
    operator_token: str = ""
    api_credentials_json: str = "{}"
    input_price_per_million_usd: float = Field(default=0.0, ge=0)
    output_price_per_million_usd: float = Field(default=0.0, ge=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings():
    return Settings()
