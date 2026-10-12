"""LangGraph with multi-specialist planning, bounded supervision and synthesis.

Untrusted history/documents can change content but never user_id, graph nodes,
permissions, or the tools' caller identity.
"""
from time import perf_counter
import asyncio
import math
import structlog
from langgraph.graph import START, END, StateGraph
from app.agents.guardrail import GuardrailAgent
from app.agents.human_escalation import HumanEscalationAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent
from app.agents.support import CustomerSupportAgent
from app.agents.synthesis import SynthesisAgent
from app.agents.web_search_agent import WebSearchAgent
from app.orchestration.state import AgentState
from app.orchestration.review_policy import choose_next, prepare_review, unresolved
from app.orchestration.privacy import (safe_public_search_query, safe_official_getnet_query,
                                       public_getnet_recovery_allowed)
from app.core.config import get_settings
from app.core.usage import add_usage, cost_usd

log = structlog.get_logger(__name__)
ALLOWED = ("knowledge", "customer_support", "web_search")


def build_graph(guardrail=None, router=None, knowledge=None, support=None, web=None,
                escalation=None, synthesis=None):
    gdr = guardrail or GuardrailAgent()
    rtr = router or RouterAgent()
    know = knowledge
    sup = support or CustomerSupportAgent()
    ws = web
    esc = escalation or HumanEscalationAgent()
    syn = synthesis or SynthesisAgent()

    def guard(s):
        started = perf_counter()
        decision = gdr.validate(s["message"])
        traces = [{"agent": "guardrail", "duration_ms": round((perf_counter()-started)*1000, 2),
                   "status": "ok" if decision["allowed"] else "blocked"}]
        if decision["allowed"]:
            return {"traces": traces, "usage_complete": True}
        return {"route": "blocked", "agent": "blocked", "plan": [],
                "agents_used": ["blocked"], "route_reason": "Bloqueado pelo guardrail",
                "answer": decision["message"], "confidence": 1.0,
                "requires_human": False, "sources": [], "tools_used": [], "traces": traces}

    def route(s):
        started = perf_counter()
        decision = rtr.route(s["message"], s["user_id"], s.get("history", []))
        raw = decision.get("plan") or [decision.get("route")]
        plan = []
        for name in raw:
            if name in ALLOWED and name not in plan:
                plan.append(name)
            elif name == "human_escalation":
                plan = ["human_escalation"]
                break
            if len(plan) >= 3:
                break
        if not plan:
            plan = ["human_escalation"]
        return {**decision, "route": plan[0], "plan": plan, "current_step": 0,
                "agent_results": [], "agents_used": [],
                "traces": [*s.get("traces", []), {"agent": "router", "duration_ms": round((perf_counter()-started)*1000,2),
                           "status": decision.get("routing_strategy", "unknown"),
                           "details": {"usage": decision.get("usage", {}), "error_codes": decision.get("errors", [])}}], "errors": decision.get("errors", []),
                "usage": decision.get("usage", {}),
                "usage_complete": (bool(decision.get("usage")) if decision.get("routing_strategy") == "llm_structured_plan"
                                   else not bool(decision.get("errors")))}

    def record(s, name, result, t0):
        entry = {"agent": name, "answer": str(result.get("answer", "")),
                 "sources": result.get("sources", []) or [],
                 "tools_used": result.get("tools_used", []) or [],
                 "confidence": float(result.get("confidence", 0)),
                 "requires_human": bool(result.get("requires_human", False)),
                 "partial_answer": str(result.get("partial_answer", "")),
                 "handoff_reason": result.get("handoff_reason", "")}
        latency = round((perf_counter() - t0) * 1000, 2)
        log.info("specialist_completed", agent=name, duration_ms=latency,
                 requires_human=entry["requires_human"])
        return {"agent": name, "answer": entry["answer"],
                "confidence": entry["confidence"],
                "requires_human": entry["requires_human"],
                "agent_results": [*s.get("agent_results", []), entry],
                "agents_used": [*s.get("agents_used", []), name],
                "current_step": s.get("current_step", 0) + 1,
                "traces": [*s.get("traces", []), *result.get("tool_spans", []), {"agent": name, "duration_ms": latency,
                  "status": "needs_human" if entry["requires_human"] else "ok",
                  "details": {"usage": result.get("usage", {}), "retrieval": result.get("retrieval", {}),
                              "error_codes": result.get("errors", [])}}],
                "errors": [*s.get("errors", []), *result.get("errors", [])],
                "usage": add_usage(s.get("usage", {}), result.get("usage", {})),
                "usage_complete": (s.get("usage_complete", True) and
                    (bool(result.get("usage")) if result.get("usage_expected", "usage" in result) else True)),
                "retrieval": result.get("retrieval", s.get("retrieval", {}))}

    def run_knowledge(s):
        nonlocal know
        t0 = perf_counter()
        try:
            know = know or KnowledgeAgent()
            result = know.process(s["message"], history=s.get("history", []))
        except Exception as exc:
            result = {"answer": "Falha na consulta RAG.", "confidence": 0.0,
                      "requires_human": True, "handoff_reason": "RAG indisponível",
                      "errors": ["knowledge:" + type(exc).__name__]}
        return record(s, "knowledge", result, t0)

    def run_support(s):
        t0 = perf_counter()
        try:
            result = sup.process(s["message"], s["user_id"], history=s.get("history", []))
        except Exception as exc:
            result = {"answer": "Falha na consulta de suporte.", "confidence": 0.0,
                      "requires_human": True, "handoff_reason": "Suporte indisponível",
                      "errors": ["customer_support:" + type(exc).__name__]}
        return record(s, "customer_support", result, t0)

    async def run_web(s):
        nonlocal ws
        t0 = perf_counter()
        try:
            ws = ws or WebSearchAgent()
            # Second enforcement point: planner output is NOT a trust boundary.
            # This applies to web-only, mixed, and Getnet fallback routes.
            if s.get("web_getnet_only"):
                public = safe_official_getnet_query(s["message"])
                if not public:
                    raise ValueError("unsafe official recovery query")
                result = await asyncio.wait_for(ws.process(public, history=[], official_only=True),
                                                timeout=get_settings().request_timeout_seconds)
            else:
                public = safe_public_search_query(
                    s["message"], mixed_private="customer_support" in s.get("plan", [])
                )
                if not public:
                    raise ValueError("unsafe public search query")
                result = await asyncio.wait_for(ws.process(public, history=[]),
                                                timeout=get_settings().request_timeout_seconds)
        except Exception as exc:
            result = {"answer": "Falha na busca web.", "confidence": 0.0,
                      "requires_human": True, "handoff_reason": "Busca web indisponível",
                      "errors": ["web_search:" + type(exc).__name__], "usage_expected": True}
        return record(s, "web_search", result, t0)

    def review(s):
        t0 = perf_counter()
        decision = prepare_review(s)
        # Bounded replanning: try official Getnet public search once if RAG
        # lacked evidence. Customer data can never cross this boundary.
        latest = (s.get("agent_results") or [{}])[-1]
        safe_public = public_getnet_recovery_allowed(s.get("message", ""))
        replanned = False
        if (latest.get("agent") == "knowledge" and latest.get("requires_human") and
                safe_public and "customer_support" not in s.get("plan", []) and
                "web_search" not in s.get("plan", []) and
                len(s.get("plan", [])) < 3 and bool(get_settings().tavily_api_key)):
            log.info("supervisor_replanning", from_agent="knowledge", to_agent="web_search")
            decision.update({"plan": [*s["plan"], "web_search"], "web_getnet_only": True})
            replanned = True
        decision["traces"] = [*s.get("traces", []), {
            "agent": "supervisor", "duration_ms": round((perf_counter()-t0)*1000, 2),
            "status": "replan" if replanned else ("unresolved" if decision.get("unresolved_agents") else "ok"),
            "details": {"results_reviewed": len(s.get("agent_results", [])),
                        "next_node": choose_next({**s, **decision}),
                        "unresolved_agents": decision.get("unresolved_agents", [])}
        }]
        return decision

    def synthesize(s):
        t0 = perf_counter()
        selected = [r for r in s.get("agent_results", []) if not r.get("requires_human")]
        try:
            result = syn.process(s["message"], selected, history=s.get("history", []))
            if not isinstance(result, dict) or not str(result.get("answer") or "").strip():
                raise ValueError("invalid synthesis result")
            confidence = float(result.get("confidence", 0))
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("invalid synthesis confidence")
        except Exception as exc:
            result = {"answer": "\n\n".join(f"[{r['agent']}] {r['answer']}" for r in selected),
                      "confidence": min(r["confidence"] for r in selected), "requires_human": False,
                      "sources": list(dict.fromkeys(v for r in selected for v in r.get("sources", []))),
                      "tools_used": list(dict.fromkeys(v for r in selected for v in r.get("tools_used", []))),
                      "errors": ["synthesis:" + type(exc).__name__], "usage_expected": True}
        multi = len(selected) > 1
        name = "synthesis" if multi else selected[0]["agent"]
        return {"agent": name, "answer": result["answer"],
                "confidence": result.get("confidence", 0), "requires_human": bool(result.get("requires_human")),
                "usage": add_usage(s.get("usage", {}), result.get("usage", {})),
                "usage_complete": (s.get("usage_complete", True) and
                    (bool(result.get("usage")) if result.get("usage_expected", False) else True)),
                "errors": [*s.get("errors", []), *result.get("errors", [])],
                "sources": result.get("sources", []), "tools_used": result.get("tools_used", []),
                "agents_used": [*s.get("agents_used", []), "synthesis"] if multi else s.get("agents_used", []),
                "traces": [*s.get("traces", []), {"agent": "synthesis", "duration_ms": round((perf_counter()-t0)*1000,2),
                           "status": "fallback" if result.get("errors") else "ok",
                           "details": {"usage": result.get("usage", {}), "error_codes": result.get("errors", [])}}]}

    def human(s):
        t0 = perf_counter()
        reason = s.get("handoff_reason") or s.get("route_reason") or "Evidência insuficiente"
        result = esc.process(reason, s["request_id"], user_id=s["user_id"],
                             conversation_id=s["conversation_id"], message=s["message"],
                             history=s.get("history", []), agent_results=s.get("agent_results", []))
        sources = list(dict.fromkeys(v for item in s.get("agent_results", []) for v in item.get("sources", [])))
        tools = list(dict.fromkeys(v for item in s.get("agent_results", []) for v in item.get("tools_used", [])))
        partial = [r["answer"] if not r.get("requires_human") else r.get("partial_answer", "")
                   for r in s.get("agent_results", [])]
        partial = [answer for answer in partial if answer]
        return {**result, "agent": "human_escalation", "sources": sources, "tools_used": tools,
                "agents_used": [*s.get("agents_used", []), "human_escalation"],
                "errors": [*s.get("errors", []), *result.get("errors", [])],
                "traces": [*s.get("traces", []), {"agent": "human_escalation", "duration_ms": round((perf_counter()-t0)*1000, 2),
                           "status": result.get("handoff_status", "unknown")}],
                "answer": (("Resultados parciais:\n" + "\n".join(partial) + "\n\n") if partial else "") + result["answer"]}

    graph = StateGraph(AgentState)
    for name, fn in [("guardrail", guard), ("router", route), ("knowledge", run_knowledge),
                     ("customer_support", run_support), ("web_search", run_web),
                     ("review", review), ("synthesis", synthesize), ("human_escalation", human)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges("guardrail", lambda s: "blocked" if s.get("route") == "blocked" else "router",
                                {"blocked": END, "router": "router"})
    possible = {"knowledge": "knowledge", "customer_support": "customer_support",
                "web_search": "web_search", "human_escalation": "human_escalation",
                "synthesis": "synthesis"}
    graph.add_conditional_edges("router", lambda s: s["plan"][0], possible)
    for name in ALLOWED:
        graph.add_edge(name, "review")
    graph.add_conditional_edges("review", choose_next, possible)
    graph.add_edge("synthesis", END)
    graph.add_edge("human_escalation", END)
    return graph.compile()
