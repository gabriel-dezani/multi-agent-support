from typing import Any, Literal, TypedDict

Route = Literal["knowledge", "customer_support", "web_search", "human_escalation", "blocked"]


class AgentState(TypedDict, total=False):
    message: str
    user_id: str
    request_id: str
    conversation_id: str
    history: list[dict[str, str]]

    route: Route
    plan: list[str]
    current_step: int
    agent: str
    agents_used: list[str]
    agent_results: list[dict[str, Any]]
    routing_strategy: str
    routing_confidence: float
    route_reason: str

    answer: str
    sources: list[str]
    tools_used: list[str]
    confidence: float
    requires_human: bool
    errors: list[str]
    retrieved_documents: list[dict[str, Any]]

    handoff_reason: str
    handoff_id: str
    handoff_status: str
    traces: list[dict[str, Any]]
    unresolved_agents: list[str]
    # Explicitly declared: LangGraph discards node updates for undeclared keys.
    usage: dict[str, int]
    usage_complete: bool
    retrieval: dict[str, float | int]
    web_getnet_only: bool
    rag_getnet_recovery: bool
