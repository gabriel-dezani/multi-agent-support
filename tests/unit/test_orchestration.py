import pytest

pytest.importorskip("langgraph")

from app.orchestration.graph import build_graph


class Guard:
    def validate(self, message):
        return {"allowed": True, "message": ""}


class Router:
    def __init__(self, plan):
        self.plan = plan

    def route(self, message, user_id, history=None):
        return {
            "route": self.plan[0],
            "plan": self.plan,
            "route_reason": "test",
            "routing_strategy": "test",
            "routing_confidence": 1.0,
        }


class FailingKnowledge:
    def process(self, message, history=None):
        return {
            "answer": "sem evidencia",
            "sources": [],
            "confidence": 0.0,
            "requires_human": True,
            "handoff_reason": "no evidence",
        }


class SuccessKnowledge:
    def process(self, message, history=None):
        return {
            "answer": "knowledge answer",
            "sources": ["https://example.com/getnet"],
            "confidence": 0.9,
            "requires_human": False,
        }


class SuccessSupport:
    def process(self, message, user_id, history=None):
        return {
            "answer": "support answer",
            "tools_used": ["get_sales_data"],
            "confidence": 0.95,
            "requires_human": False,
        }


class FailingSupport:
    def process(self, message, user_id, history=None):
        return {
            "answer": "falha",
            "tools_used": ["get_sales_data"],
            "confidence": 0.2,
            "requires_human": True,
            "handoff_reason": "tool failed",
        }


class Synthesis:
    def process(self, message, agent_results, history=None):
        return {
            "answer": " | ".join(r["answer"] for r in agent_results),
            "sources": [s for r in agent_results for s in r.get("sources", [])],
            "tools_used": [t for r in agent_results for t in r.get("tools_used", [])],
            "confidence": 0.9,
            "requires_human": False,
        }


class Escalation:
    def process(self, reason, request_id, **kwargs):
        return {
            "answer": "queued",
            "confidence": 0.0,
            "requires_human": True,
            "sources": [],
            "tools_used": [],
            "handoff_id": "handoff-test",
            "handoff_status": "pending",
        }


def state(message="unknown"):
    return {
        "message": message,
        "user_id": "cliente1988",
        "request_id": "req-1",
        "conversation_id": "conv-1",
        "history": [],
        "sources": [],
        "tools_used": [],
        "errors": [],
        "agent_results": [],
        "agents_used": [],
    }


def test_knowledge_low_evidence_creates_real_handoff_result():
    graph = build_graph(
        guardrail=Guard(),
        router=Router(["knowledge"]),
        knowledge=FailingKnowledge(),
        support=FailingSupport(),
        escalation=Escalation(),
    )
    result = graph.invoke(state())
    assert result["agent"] == "human_escalation"
    assert result["requires_human"] is True
    assert result["handoff_id"] == "handoff-test"


def test_multi_agent_plan_executes_two_specialists_and_synthesizes():
    graph = build_graph(
        guardrail=Guard(),
        router=Router(["knowledge", "customer_support"]),
        knowledge=SuccessKnowledge(),
        support=SuccessSupport(),
        escalation=Escalation(),
        synthesis=Synthesis(),
    )
    result = graph.invoke(state("Explain Pix and check my payout"))
    assert result["agent"] == "synthesis"
    assert result["agents_used"] == ["knowledge", "customer_support", "synthesis"]
    assert result["requires_human"] is False
    assert "knowledge answer" in result["answer"]
    assert "support answer" in result["answer"]


def test_direct_human_route_creates_handoff():
    graph = build_graph(
        guardrail=Guard(),
        router=Router(["human_escalation"]),
        knowledge=FailingKnowledge(),
        support=FailingSupport(),
        escalation=Escalation(),
    )
    result = graph.invoke(state("I need a human agent"))
    assert result["agent"] == "human_escalation"
    assert result["handoff_status"] == "pending"
