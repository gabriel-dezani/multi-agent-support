import json
from pathlib import Path
from app.agents.router import RouterAgent


def test_all_ten_examples_are_present_and_route_correctly():
    dataset = json.loads(Path("data/evaluation_dataset.json").read_text(encoding="utf-8"))
    assert len(dataset) == 10
    router = RouterAgent()
    results = [router.route(row["message"], row["user_id"])["route"] == row["expected_route"] for row in dataset]
    assert all(results)
