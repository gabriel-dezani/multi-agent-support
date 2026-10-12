from app.agents.synthesis import SynthesisAgent


def test_synthesis_combines_multiple_specialists_without_llm():
    agent = SynthesisAgent(llm=None)
    results = [
        {
            "agent": "knowledge",
            "answer": "Pix evidence",
            "sources": ["https://example.com/pix"],
            "tools_used": [],
            "confidence": 0.8,
        },
        {
            "agent": "customer_support",
            "answer": "Payout status",
            "sources": [],
            "tools_used": ["get_sales_data"],
            "confidence": 0.9,
        },
    ]
    result = agent.process("mixed question", results, history=[])
    assert "Pix evidence" in result["answer"]
    assert "Payout status" in result["answer"]
    assert result["sources"] == ["https://example.com/pix"]
    assert result["tools_used"] == ["get_sales_data"]
    assert result["requires_human"] is False


def test_synthesis_without_results_requests_human():
    result = SynthesisAgent().process("question", [], history=[])
    assert result["requires_human"] is True
    assert result["confidence"] == 0.0
