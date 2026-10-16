"""Offline safety contract for partial answers during web-provider failures.

No LLM, Tavily, network calls, LangGraph installation, or credentials needed.
"""

import pytest

from app.orchestration.review_policy import (
    usable_specialist_result, unresolved, choose_next,
)


@pytest.mark.parametrize("result,expected", [
    ({"agent": "customer_support", "answer": "Vendas confirmadas", "tools_used": ["get_sales_data"],
      "confidence": 0.95, "requires_human": False}, True),
    ({"agent": "knowledge", "answer": "Pix com fonte", "sources": ["https://site.getnet.com.br/pix/"],
      "confidence": 0.95, "requires_human": False}, True),
    ({"agent": "customer_support", "answer": "Sem dados", "tools_used": [],
      "confidence": 0.95, "requires_human": False}, False),
    ({"agent": "knowledge", "answer": "Afirmação sem fonte", "sources": [],
      "confidence": 0.95, "requires_human": False}, False),
    ({"agent": "customer_support", "answer": "", "tools_used": ["get_sales_data"],
      "confidence": 0.95, "requires_human": False}, False),
    ({"agent": "customer_support", "answer": "Falha", "tools_used": ["get_sales_data"],
      "confidence": 0.95, "requires_human": True}, False),
    ({"agent": "customer_support", "answer": "Vendas", "tools_used": ["get_sales_data"],
      "confidence": 0.1, "requires_human": False}, False),
    ({"agent": "web_search", "answer": "Informação web", "sources": ["https://example.org"],
      "confidence": 0.95, "requires_human": False}, False),
    ({"agent": "knowledge", "answer": "", "sources": ["https://example.org"],
      "confidence": 0.95, "requires_human": False}, False),
])
def test_only_verified_previous_specialist_can_enable_partial_degradation(result, expected):
    assert usable_specialist_result(result) is expected


def test_provider_outage_not_an_unresolved_customer_question():
    support = {"agent": "customer_support", "answer": "Vendas disponíveis",
               "tools_used": ["get_sales_data"], "confidence": 0.9,
               "requires_human": False}
    failed_web = {"agent": "web_search", "answer": "", "sources": [],
                  "confidence": 0.0, "provider_unavailable": True,
                  "requires_human": False}
    state = {"plan": ["customer_support", "web_search"], "current_step": 2,
             "agent_results": [support, failed_web]}
    assert unresolved(state) == []
    assert choose_next(state) == "synthesis"


def test_genuine_web_evidence_failure_still_requires_a_human():
    state = {"plan": ["web_search"], "current_step": 1,
             "agent_results": [{"agent": "web_search", "answer": "Nenhuma fonte",
                                "sources": [], "confidence": 0.0,
                                "requires_human": True}]}
    assert unresolved(state) == ["web_search"]
    assert choose_next(state) == "human_escalation"
