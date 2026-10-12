import pytest

pytest.importorskip("langchain_core")

from app.agents.router import RouterAgent, RoutingDecision


class FakeStructured:
    def invoke(self, messages):
        return RoutingDecision(
            plan=["knowledge", "customer_support"],
            reason="A pergunta mistura produto e dados pessoais.",
            confidence=0.93,
        )


class FakeLLM:
    def with_structured_output(self, schema):
        assert schema is RoutingDecision
        return FakeStructured()


def test_llm_router_returns_ordered_multi_agent_plan():
    result = RouterAgent(llm=FakeLLM(), enable_llm=True).route(
        "Explain Pix and check yesterday's payout",
        "cliente1988",
        history=[{"role": "user", "content": "I use Getnet"}],
    )
    assert result["plan"] == ["knowledge", "customer_support"]
    assert result["routing_strategy"] == "llm_structured_plan"
    assert result["routing_confidence"] == pytest.approx(0.93)
