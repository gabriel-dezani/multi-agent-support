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


def _weak_result(result: dict) -> bool:
    """Uniform review of usable evidence independent of an agent's own verdict."""
    if result.get("requires_human") or result.get('provider_unavailable'):
        return True
    if "answer" in result and not str(result.get("answer") or "").strip():
        return True
    if result.get("agent") in {"knowledge", "web_search"} and "sources" in result:
        if not result["sources"]:
            return True
    if result.get("agent") == "customer_support" and "tools_used" in result:
        if not result["tools_used"]:
            return True
    if "confidence" in result:
        try:
            import math
            confidence = float(result["confidence"])
        except (TypeError, ValueError, OverflowError):
            return True
        if not math.isfinite(confidence) or not 0.35 <= confidence <= 1:
            return True
    return False


def usable_specialist_result(result: dict) -> bool:
    """A verified, completed specialist result can support partial degradation.

    In particular, a web-provider outage can never make an otherwise empty
    response succeed, and unsupported documents/failed account tools are not
    treated as valid partial evidence.
    """
    specialist = result.get("agent")
    if specialist not in {"knowledge", "customer_support"}:
        return False
    # Evidence is mandatory here even when an older caller omitted the field.
    evidence = (result.get("sources") if specialist == "knowledge"
                else result.get("tools_used"))
    return (bool(str(result.get("answer") or "").strip())
            and bool(evidence)
            and not result.get("provider_unavailable")
            and not _weak_result(result))


def unresolved(state: dict) -> list[str]:
    """Count knowledge retrieval failure as recovered only if official-web fallback succeeded."""
    results = state.get("agent_results", [])
    resolved_by_official_web = bool(
        state.get("web_getnet_only") and any(
            r.get("agent") == "web_search" and not _weak_result(r) and
            bool(str(r.get("answer") or "").strip()) and r.get("sources")
            and not r.get("provider_unavailable") for r in results
        )
    )
    resolved_by_local_rag = bool(
        state.get("rag_getnet_recovery") and any(
            r.get("agent") == "knowledge" and usable_specialist_result(r) for r in results
        )
    )
    return [str(r.get("agent", "unknown")) for r in results
            if not r.get("provider_unavailable") and _weak_result(r) and not (
                (resolved_by_official_web and r.get("agent") == "knowledge") or
                (resolved_by_local_rag and r.get("agent") == "web_search"))]


def bounded_replan(state: dict, *, web_available: bool, max_agents: int = 3,
                   knowledge_available: bool = True) -> dict:
    """One-step, deterministic replan from specialist evidence, never from LLM tools.

    A public Getnet question may switch between local RAG and official web
    once. Customer-specific requests NEVER get sent to public providers.
    """
    from app.orchestration.privacy import public_getnet_recovery_allowed

    plan = list(state.get("plan") or [])
    results = state.get("agent_results") or []
    if not plan or not results or len(plan) >= min(max_agents, 3):
        return {}
    latest = results[-1]
    # A tool/policy denial is not evidence that another public provider should
    # be tried. Preserve the security boundary even if confidence is low.
    denied = {'privacy_blocked','unauthorized_tool','prompt_injection'}
    if any(str(error).split(':')[-1].strip() in denied for error in latest.get('errors', [])):
        return {}
    if latest.get("agent") not in {"knowledge", "web_search"} or not _weak_result(latest):
        return {}
    if "customer_support" in plan or not public_getnet_recovery_allowed(state.get("message", "")):
        return {}
    if latest["agent"] == "knowledge" and web_available and "web_search" not in plan:
        return {"plan": [*plan, "web_search"], "web_getnet_only": True}
    if latest["agent"] == "web_search" and knowledge_available and "knowledge" not in plan:
        return {"plan": [*plan, "knowledge"], "rag_getnet_recovery": True}
    return {}
