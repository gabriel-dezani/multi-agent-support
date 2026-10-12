import argparse
import json
import os
from pathlib import Path

import httpx

from app.agents.router import RouterAgent


def _router_eval(scenarios, use_llm: bool):
    router = RouterAgent(enable_llm=use_llm)
    results = []
    correct = 0
    total = 0

    for scenario in scenarios:
        history = []
        for turn in scenario["turns"]:
            decision = router.route(turn["message"], scenario["user_id"], history=history)
            route_ok = decision["route"] == turn["expected_route"]
            plan_ok = True
            if "expected_plan" in turn:
                plan_ok = decision["plan"] == turn["expected_plan"]
            ok = route_ok and plan_ok
            correct += int(ok)
            total += 1
            results.append({
                "scenario": scenario["id"],
                "message": turn["message"],
                "expected_route": turn["expected_route"],
                "predicted_route": decision["route"],
                "expected_plan": turn.get("expected_plan"),
                "predicted_plan": decision["plan"],
                "ok": ok,
            })
            history.append({"role": "user", "content": turn["message"]})
            history.append({"role": "assistant", "content": "placeholder response for routing context"})

    return {
        "mode": "router",
        "turn_accuracy": correct / total if total else 0.0,
        "turns": total,
        "passed_turns": correct,
        "results": results,
    }


def _api_eval(scenarios, base_url: str, token: str):
    results = []
    correct = 0
    total = 0
    with httpx.Client(base_url=base_url, timeout=60,
                      headers={"Authorization": f"Bearer {token}"}) as client:
        for scenario in scenarios:
            conversation_id = None
            for turn in scenario["turns"]:
                payload = {"message": turn["message"], "user_id": scenario["user_id"]}
                if conversation_id:
                    payload["conversation_id"] = conversation_id
                response = client.post("/chat", json=payload)
                response.raise_for_status()
                body = response.json()
                conversation_id = body["conversation_id"]
                predicted_plan = body.get("plan") or [body.get("agent")]
                predicted_route = predicted_plan[0]
                route_ok = predicted_route == turn["expected_route"]
                plan_ok = True
                if "expected_plan" in turn:
                    plan_ok = predicted_plan == turn["expected_plan"]
                ok = route_ok and plan_ok
                correct += int(ok)
                total += 1
                results.append({
                    "scenario": scenario["id"],
                    "message": turn["message"],
                    "conversation_id": conversation_id,
                    "expected_route": turn["expected_route"],
                    "predicted_route": predicted_route,
                    "expected_plan": turn.get("expected_plan"),
                    "predicted_plan": predicted_plan,
                    "agents_used": body.get("agents_used", []),
                    "requires_human": body.get("requires_human", False),
                    "ok": ok,
                })
    return {
        "mode": "api",
        "turn_accuracy": correct / total if total else 0.0,
        "turns": total,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-turn and multi-agent evaluation")
    parser.add_argument("--dataset", default="data/evaluation_multiturn.json")
    parser.add_argument("--mode", choices=["router", "api"], default="router")
    parser.add_argument("--llm-router", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("EVAL_BEARER_TOKEN", ""),
                        help="Local test user token, or set EVAL_BEARER_TOKEN")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.mode == "api" and not args.token:
        parser.error("API mode requires --token or EVAL_BEARER_TOKEN")

    scenarios = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    report = _router_eval(scenarios, args.llm_router) if args.mode == "router" else _api_eval(scenarios, args.base_url, args.token)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
