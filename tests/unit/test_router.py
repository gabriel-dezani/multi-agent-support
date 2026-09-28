import json
from pathlib import Path
from app.agents.router import RouterAgent


def test_challenge_routes():
    router = RouterAgent()
    for row in json.loads(Path("data/evaluation_dataset.json").read_text(encoding="utf-8")):
        assert router.route(row["message"], row["user_id"])["route"] == row["expected_route"]


def test_router_handles_paraphrases_without_substring_false_positives():
    router = RouterAgent()
    assert router.route("What is the weather today?", "cliente1988")["route"] == "web_search"
    assert router.route("My payment was declined", "cliente1988")["route"] == "customer_support"
    assert router.route("I need help with a sale", "cliente1988")["route"] == "customer_support"
    assert router.route("Can I talk to a human agent?", "cliente1988")["route"] == "human_escalation"
    assert router.route("What is the product difference?", "cliente1988")["route"] == "knowledge"


def test_router_uses_human_for_conflicting_intents():
    router = RouterAgent()
    result = router.route("My terminal is offline; what is the exchange rate today?", "cliente1988")
    assert result["route"] == "human_escalation"
