from types import SimpleNamespace

from app.agents.support import CustomerSupportAgent
from app.agents.synthesis import SynthesisAgent
from app.orchestration.privacy import safe_public_subquery, public_getnet_recovery_allowed


class BrokenSalesRepository:
    def get_by_user_id(self, user_id):
        assert user_id == "alice"  # authenticated identity must stay server-side
        return {"terminal": {"model": "Get Smart", "connection": "online", "last_sync": "now"}}


def test_partial_support_tool_failure_keeps_success_and_requests_operator():
    response = CustomerSupportAgent(BrokenSalesRepository()).process(
        "My terminal cannot connect and I need my sales payout", "alice"
    )
    assert response["requires_human"]
    assert "Terminal Get Smart" in response["answer"]
    assert response["tools_used"] == ["get_terminal_status", "get_sales_data"]
    assert [span["status"] for span in response["tool_spans"]] == ["ok", "unavailable"]


class ForbiddenLLM:
    def invoke(self, *args, **kwargs):
        raise AssertionError("private account data leaked to an external LLM")


def test_synthesis_never_calls_llm_for_customer_account_results():
    out = SynthesisAgent(llm=ForbiddenLLM()).process(
        "Explain Pix and my sales", [
            {"agent": "knowledge", "answer": "Pix public answer", "confidence": .8},
            {"agent": "customer_support", "answer": "PRIVATE-SALES-DATA", "confidence": .9},
        ], history=[{"role": "user", "content": "very private customer history"}]
    )
    assert "PRIVATE-SALES-DATA" in out["answer"]
    assert not out["requires_human"]


def test_public_search_for_mixed_private_request_is_minimal_and_private_free():
    incoming = "My sales of R$ 123456 on CPF 123.456.789-00 and euro exchange rate today?"
    query = safe_public_subquery(incoming)
    assert query == "current EUR BRL exchange rate"
    assert all(part not in query for part in ["123", "sales", "CPF"])
    assert safe_public_subquery("My sales plus random trivia about customer Alice") is None
    assert not public_getnet_recovery_allowed("My Getnet account and payout, CPF 11111111111")
    assert public_getnet_recovery_allowed("How does Getnet Pix work?")
