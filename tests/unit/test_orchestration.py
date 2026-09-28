import pytest

pytest.importorskip("langgraph")

from app.orchestration.graph import build_graph


class Guard:
    def validate(self, message):
        return {"allowed": True, "message": ""}


class Router:
    def __init__(self, route):
        self.route_name = route

    def route(self, message, user_id):
        return {"route": self.route_name, "route_reason": "test"}


class FailingKnowledge:
    def process(self, message):
        return {
            "answer": "sem evidencia",
            "sources": [],
            "confidence": 0.0,
            "requires_human": True,
            "handoff_reason": "no evidence",
        }


class FailingSupport:
    def process(self, message, user_id):
        return {
            "answer": "falha",
            "tools_used": ["get_sales_data"],
            "confidence": 0.2,
            "requires_human": True,
            "handoff_reason": "tool failed",
        }


def test_knowledge_low_evidence_is_handed_to_human():
    graph = build_graph(
        guardrail=Guard(),
        router=Router("knowledge"),
        knowledge=FailingKnowledge(),
        support=FailingSupport(),
    )
    result = graph.invoke({
        "message": "unknown",
        "user_id": "cliente1988",
        "request_id": "req-1",
        "sources": [],
        "tools_used": [],
        "errors": [],
    })
    assert result["agent"] == "human_escalation"
    assert result["requires_human"] is True
    assert result["request_id"] == "req-1"


def test_direct_human_route_is_handed_to_human():
    graph = build_graph(
        guardrail=Guard(),
        router=Router("human_escalation"),
        knowledge=FailingKnowledge(),
        support=FailingSupport(),
    )
    result = graph.invoke({
        "message": "I need a human agent",
        "user_id": "cliente1988",
        "request_id": "req-2",
        "sources": [],
        "tools_used": [],
        "errors": [],
    })
    assert result["agent"] == "human_escalation"
    assert result["requires_human"] is True
