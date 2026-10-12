from app.handoff.repository import HandoffRepository
from app.agents.human_escalation import HumanEscalationAgent


def test_human_escalation_creates_and_resolves_durable_case(tmp_path):
    repo = HandoffRepository(str(tmp_path / "state.db"))
    agent = HumanEscalationAgent(repository=repo)
    result = agent.process(
        "low evidence",
        "req-1",
        user_id="cliente1988",
        conversation_id="conv-1",
        message="I need help",
        history=[],
        agent_results=[],
    )
    assert result["requires_human"] is True
    assert result["handoff_status"] == "pending"
    assert result["handoff_id"].startswith("handoff-")

    resolved = repo.resolve(result["handoff_id"], resolution="Handled by operator", resolved_by="agent-1")
    assert resolved["status"] == "resolved"
    assert resolved["resolution"] == "Handled by operator"
