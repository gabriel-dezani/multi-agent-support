from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator

AgentName = Literal[
    "knowledge",
    "customer_support",
    "web_search",
    "human_escalation",
    "synthesis",
    "blocked",
]

Identifier = r"^[A-Za-z0-9._:-]+$"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(min_length=1, max_length=100, pattern=Identifier)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=Identifier)

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value):
        if not value.strip():
            raise ValueError("message must contain non-whitespace text")
        return value


class ChatResponse(BaseModel):
    answer: str
    agent: AgentName
    route_reason: str
    tools_used: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    requires_human: bool = False
    request_id: str
    conversation_id: str
    plan: list[str] = Field(default_factory=list)
    agents_used: list[str] = Field(default_factory=list)
    routing_strategy: str = ""
    routing_confidence: float = Field(default=0.0, ge=0, le=1)
    handoff_id: str | None = None
    handoff_status: str | None = None


class HandoffResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(min_length=1, max_length=4000)
    # Retained for backwards compatibility with v4 clients, but ignored by API.
    # The authenticated operator is the only valid audit identity.
    resolved_by: str | None = Field(default=None, min_length=1, max_length=100, pattern=Identifier)

    @field_validator("resolution")
    @classmethod
    def nonblank_resolution(cls, value):
        if not value.strip():
            raise ValueError("resolution must contain non-whitespace text")
        return value


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=100)
    rating: int = Field(ge=1, le=5)
