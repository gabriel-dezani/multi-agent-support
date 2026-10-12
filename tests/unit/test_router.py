import json
from pathlib import Path

from app.agents.router import RouterAgent


def test_challenge_routes():
    router = RouterAgent(enable_llm=False)
    for row in json.loads(Path("data/evaluation_dataset.json").read_text(encoding="utf-8")):
        assert router.route(row["message"], row["user_id"])["route"] == row["expected_route"]


def test_router_handles_paraphrases_without_substring_false_positives():
    router = RouterAgent(enable_llm=False)
    assert router.route("What is the weather today?", "cliente1988")["route"] == "web_search"
    assert router.route("My payment was declined", "cliente1988")["route"] == "customer_support"
    assert router.route("I need help with a sale", "cliente1988")["route"] == "customer_support"
    assert router.route("Can I talk to a human agent?", "cliente1988")["route"] == "human_escalation"
    assert router.route("What is the product difference?", "cliente1988")["route"] == "knowledge"


def test_router_builds_multi_agent_plan_for_mixed_intents():
    router = RouterAgent(enable_llm=False)
    result = router.route("My terminal is offline; what is the exchange rate today?", "cliente1988")
    assert result["route"] == "customer_support"
    assert result["plan"] == ["customer_support", "web_search"]


def test_router_uses_recent_user_context_for_elliptical_follow_up():
    router = RouterAgent(enable_llm=False)
    history = [{"role": "user", "content": "My card machine is offline"}]
    result = router.route("And now what should I do?", "cliente1988", history=history)
    assert result["route"] == "customer_support"


def test_router_can_plan_knowledge_plus_support_without_llm():
    router = RouterAgent(enable_llm=False)
    result = router.route(
        "Explain Pix and check yesterday's payout",
        "cliente1988",
    )
    assert result["plan"] == ["knowledge", "customer_support"]


def test_new_topic_does_not_inherit_previous_support_intent_in_fallback():
    router = RouterAgent(enable_llm=False)
    history = [{"role": "user", "content": "My card machine is offline"}]
    result = router.route("How does the Payment Link work?", "cliente1988", history=history)
    assert result["plan"] == ["knowledge"]
