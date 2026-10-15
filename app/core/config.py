from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    tavily_api_key: str = ""

    vector_store_path: str = ".vector_data"
    rag_collection: str = "getnet_products"
    rag_top_k: int = Field(default=4, ge=1, le=20)
    rag_min_relevance: float = Field(default=0.45, ge=0.0, le=1.0)
    rag_hybrid_enabled: bool = True
    rag_candidate_multiplier: int = Field(default=3, ge=1, le=5)
    rag_lexical_max_chunks: int = Field(default=1500, ge=50, le=10000)
    rag_max_chunks_per_source: int = Field(default=2, ge=1, le=10)
    rag_rerank_rrf_k: int = Field(default=60, ge=1, le=200)
    rag_verifier_mode: Literal["heuristic", "llm"] = "heuristic"  # heuristic | llm (fail-closed on errors)
    rag_verifier_min_score: float = Field(default=0.85, ge=0, le=1)

    request_timeout_seconds: float = Field(default=15, gt=0, le=120)
    total_request_timeout_seconds: float = Field(default=90, gt=0, le=600)

    # Agentic routing: use an LLM structured classifier when a key is available,
    # with a deterministic fallback for resilience and offline tests.
    router_use_llm: bool = True
    router_max_agents: int = Field(default=3, ge=1, le=4)

    # Durable local state for multi-turn memory and human-handoff queue.
    state_db_path: str = ".state/support.db"
    state_backend: Literal["sqlite", "postgres"] = "sqlite"
    state_database_url: str = ""  # PG backend only, never committed to VCS
    replicas: int = Field(default=1, ge=1, le=100)
    memory_max_messages: int = Field(default=12, ge=2, le=50)
    memory_retention_days: int = Field(default=0, ge=0, le=3650)  # 0 = retain until explicit deletion
    otlp_endpoint: str = ""
    otlp_service_name: str = "multi-agent-support"

    # Operator endpoints are protected by an explicit token. Leave blank to
    # disable operator actions until a secret is configured.
    operator_token: str = ""
    # Optional corporate OIDC verification. In oidc mode local credentials and
    # X-Operator-Token are NEVER accepted as alternate authentication paths.
    auth_mode: Literal["local", "oidc"] = "local"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_user_claim: str = "sub"
    oidc_role_claim: str = "role"
    oidc_customer_role: str = "customer"
    oidc_operator_role: str = "operator"
    api_credentials_json: str = "{}"
    input_price_per_million_usd: float = Field(default=0.0, ge=0)
    output_price_per_million_usd: float = Field(default=0.0, ge=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings():
    return Settings()
