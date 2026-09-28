from langgraph.graph import END, START, StateGraph
from app.orchestration.state import AgentState
from app.agents.guardrail import GuardrailAgent
from app.agents.router import RouterAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.support import CustomerSupportAgent
from app.agents.web_search_agent import WebSearchAgent
from app.agents.human_escalation import HumanEscalationAgent


def build_graph(guardrail=None, router=None, knowledge=None, support=None, web=None, escalation=None):
    gdr = guardrail or GuardrailAgent()
    rtr = router or RouterAgent()
    know = knowledge
    sup = support or CustomerSupportAgent()
    ws = web
    esc = escalation or HumanEscalationAgent()

    def guard(s):
        value = gdr.validate(s["message"])
        if value["allowed"]:
            return s
        return {
            **s,
            "route": "blocked",
            "agent": "blocked",
            "route_reason": "Entrada bloqueada pelo guardrail.",
            "answer": value["message"],
            "confidence": 1.0,
            "requires_human": False,
        }

    def route(s):
        return {**s, **rtr.route(s["message"], s["user_id"])}

    def knowledge_node(s):
        nonlocal know
        know = know or KnowledgeAgent()
        result = know.process(s["message"])
        return {**s, "agent": "knowledge", **result}

    def support_node(s):
        result = sup.process(s["message"], s["user_id"])
        return {**s, "agent": "customer_support", **result}

    async def web_node(s):
        nonlocal ws
        ws = ws or WebSearchAgent()
        try:
            result = await ws.process(s["message"])
        except Exception as exc:
            result = {
                "answer": "Não foi possível consultar informações atuais. A solicitação será encaminhada para atendimento humano.",
                "sources": [],
                "tools_used": ["web_search"],
                "confidence": 0.0,
                "requires_human": True,
                "errors": [f"web_search: {type(exc).__name__}"],
                "handoff_reason": "Falha controlada na dependência de busca web.",
            }
        return {**s, "agent": "web_search", **result}

    def escalation_node(s):
        reason = s.get("handoff_reason") or s.get("route_reason") or "Baixa confiança, falta de evidência ou falha controlada."
        return {**s, "agent": "human_escalation", **esc.process(reason, s["request_id"])}

    def after_agent(s):
        return "human_escalation" if s.get("requires_human") else END

    graph = StateGraph(AgentState)
    for name, fn in (
        ("guardrail", guard),
        ("router", route),
        ("knowledge", knowledge_node),
        ("customer_support", support_node),
        ("web_search", web_node),
        ("human_escalation", escalation_node),
    ):
        graph.add_node(name, fn)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges(
        "guardrail",
        lambda s: "blocked" if s.get("route") == "blocked" else "router",
        {"blocked": END, "router": "router"},
    )
    graph.add_conditional_edges(
        "router",
        lambda s: s["route"],
        {
            "knowledge": "knowledge",
            "customer_support": "customer_support",
            "web_search": "web_search",
            "human_escalation": "human_escalation",
        },
    )
    for node in ("knowledge", "customer_support", "web_search"):
        graph.add_conditional_edges(node, after_agent, {"human_escalation": "human_escalation", END: END})
    graph.add_edge("human_escalation", END)
    return graph.compile()
