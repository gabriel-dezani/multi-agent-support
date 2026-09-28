from typing import Any, Literal, TypedDict

Route = Literal["knowledge", "customer_support", "web_search", "human_escalation", "blocked"]


class AgentState(TypedDict, total=False):
    message: str
    user_id: str
    request_id: str
    route: Route
    agent: str
    route_reason: str
    answer: str
    sources: list[str]
    tools_used: list[str]
    confidence: float
    requires_human: bool
    errors: list[str]
    retrieved_documents: list[dict[str, Any]]
    handoff_reason: str
