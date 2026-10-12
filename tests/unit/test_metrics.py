from app.core.metrics import MetricsRegistry


def test_metrics_tracks_requests_handoffs_agents_plans_and_latency():
    registry = MetricsRegistry()
    registry.record(
        route="knowledge",
        agents=["knowledge"],
        handoff=False,
        latency_ms=10,
        error=False,
        degraded=False,
        plan=["knowledge"],
        routing_strategy="llm_structured_plan",
    )
    registry.record(
        route="customer_support",
        agents=["customer_support", "web_search", "synthesis"],
        handoff=True,
        latency_ms=30,
        error=False,
        degraded=True,
        plan=["customer_support", "web_search"],
        routing_strategy="deterministic_fallback",
    )
    registry.record_handoff_resolution(42.0)

    snapshot = registry.snapshot()
    assert snapshot["requests_total"] == 2
    assert snapshot["handoffs_total"] == 1
    assert snapshot["handoffs_resolved_total"] == 1
    assert snapshot["degraded_requests_total"] == 1
    assert snapshot["multi_agent_requests_total"] == 1
    assert snapshot["multi_agent_rate"] == 0.5
    assert snapshot["routes"]["knowledge"] == 1
    assert snapshot["agents"]["synthesis"] == 1
    assert snapshot["routing_strategies"]["llm_structured_plan"] == 1
    assert snapshot["plan_lengths"]["2"] == 1
    assert snapshot["latency_ms"]["p95"] >= 10
    assert snapshot["handoff_resolution_seconds"]["p50"] == 42.0
