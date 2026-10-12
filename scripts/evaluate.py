import argparse
import json
import os
import time
from pathlib import Path

import httpx

from app.agents.router import RouterAgent


def load_dataset(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ratio(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def router_eval(dataset, use_llm: bool):
    router = RouterAgent(enable_llm=use_llm)
    rows = []
    started = time.perf_counter()
    for case in dataset:
        decision = router.route(case["message"], case["user_id"], history=[])
        predicted = decision["plan"][0]
        rows.append({
            "id": case["id"],
            "expected": case["expected_route"],
            "predicted": predicted,
            "plan": decision["plan"],
            "strategy": decision.get("routing_strategy"),
            "routing_confidence": decision.get("routing_confidence"),
            "ok": predicted == case["expected_route"],
        })
    elapsed = (time.perf_counter() - started) * 1000
    return {
        "mode": "router",
        "route_accuracy": _ratio([r["ok"] for r in rows]),
        "cases": len(rows),
        "latency_ms_total": round(elapsed, 2),
        "results": rows,
    }


def api_eval(dataset, base_url: str, token: str):
    rows = []
    latencies = []
    with httpx.Client(base_url=base_url, timeout=60,
                      headers={"Authorization": f"Bearer {token}"}) as client:
        for case in dataset:
            started = time.perf_counter()
            response = client.post("/chat", json={"message": case["message"], "user_id": case["user_id"]})
            latency = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            body = response.json()
            predicted = (body.get("plan") or [body.get("agent")])[0]
            route_ok = predicted == case["expected_route"]
            expected_tool = case.get("expected_tool")
            tool_ok = None if not expected_tool else expected_tool in body.get("tools_used", [])
            expect_sources = case.get("expect_sources")
            source_ok = None if expect_sources is None else bool(body.get("sources")) == bool(expect_sources)
            expected_handoff = case.get("expected_requires_human")
            handoff_ok = None if expected_handoff is None else bool(body.get("requires_human")) == bool(expected_handoff)
            answer_ok = bool(str(body.get("answer", "")).strip())
            rows.append({
                "id": case["id"],
                "expected_route": case["expected_route"],
                "predicted_route": predicted,
                "route_ok": route_ok,
                "agent": body.get("agent"),
                "agents_used": body.get("agents_used", []),
                "plan": body.get("plan", []),
                "routing_strategy": body.get("routing_strategy"),
                "requires_human": body.get("requires_human", False),
                "handoff_ok": handoff_ok,
                "sources": body.get("sources", []),
                "source_ok": source_ok,
                "tools_used": body.get("tools_used", []),
                "tool_ok": tool_ok,
                "answer_ok": answer_ok,
                "latency_ms": round(latency, 2),
            })
            latencies.append(latency)

    tool_checks = [r["tool_ok"] for r in rows if r["tool_ok"] is not None]
    source_checks = [r["source_ok"] for r in rows if r["source_ok"] is not None]
    handoff_checks = [r["handoff_ok"] for r in rows if r["handoff_ok"] is not None]
    return {
        "mode": "api",
        "cases": len(rows),
        "route_accuracy": _ratio([r["route_ok"] for r in rows]),
        "tool_accuracy": _ratio(tool_checks),
        "source_coverage_accuracy": _ratio(source_checks),
        "handoff_accuracy": _ratio(handoff_checks),
        "answer_success_rate": _ratio([r["answer_ok"] for r in rows]),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "handoff_rate": round(sum(r["requires_human"] for r in rows) / len(rows), 4) if rows else 0.0,
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluation runner for the multi-agent support system")
    parser.add_argument("--dataset", default="data/evaluation_dataset.json")
    parser.add_argument("--mode", choices=["router", "api"], default="router")
    parser.add_argument("--llm-router", action="store_true", help="Use the structured LLM router in router mode")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("EVAL_BEARER_TOKEN", ""),
                        help="Local test user token, or set EVAL_BEARER_TOKEN")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.mode == "api" and not args.token:
        parser.error("API mode requires --token or EVAL_BEARER_TOKEN")

    dataset = load_dataset(args.dataset)
    report = router_eval(dataset, args.llm_router) if args.mode == "router" else api_eval(dataset, args.base_url, args.token)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
