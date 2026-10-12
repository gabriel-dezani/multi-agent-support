"""Pure, bounded supervisor decisions. Easy to evaluate without any LLM or I/O."""


def choose_next(state: dict) -> str:
    """Run remaining specialists before escalating a failed subtask.

    No arbitrary LLM-generated node names are honored. Never loop: each
    specialist advances current_step, and router plans are bounded.
    """
    plan = state.get("plan", [])
    position = int(state.get("current_step", 0))
    allowed = {"knowledge", "customer_support", "web_search"}
    while position < len(plan):
        step = plan[position]
        if step in allowed:
            return step
        if step == "human_escalation":
            return "human_escalation"
        position += 1
    results = state.get("agent_results", [])
    if not results or unresolved(state):
        return "human_escalation"
    return "synthesis"


def prepare_review(state: dict) -> dict:
    """Keep partial successful evidence and mark unresolved subtasks."""
    results = state.get("agent_results", [])
    failed = unresolved(state)
    return {
        "unresolved_agents": failed,
        "handoff_reason": (
            "Especialistas com resultado insuficiente: " + ", ".join(failed)
            if failed else state.get("handoff_reason", "")
        ),
    }


def unresolved(state: dict) -> list[str]:
    """Count knowledge retrieval failure as recovered only if official-web fallback succeeded."""
    results = state.get("agent_results", [])
    resolved_by_official_web = bool(
        state.get("web_getnet_only") and any(
            r.get("agent") == "web_search" and not r.get("requires_human") and
            r.get("sources") for r in results
        )
    )
    def is_weak(result: dict) -> bool:
        if result.get("requires_human"):
            return True
        if "answer" in result and not str(result.get("answer") or "").strip():
            return True
        # Guard against an apparently successful but ungrounded specialist.
        if result.get("agent") in {"knowledge", "web_search"} and "sources" in result:
            if not result["sources"]:
                return True
        if result.get("agent") == "customer_support" and "tools_used" in result:
            if not result["tools_used"]:
                return True
        if "confidence" in result and float(result["confidence"] or 0) < 0.35:
            return True
        return False

    return [str(r.get("agent", "unknown")) for r in results
            if is_weak(r) and not (
                resolved_by_official_web and r.get("agent") == "knowledge")]
