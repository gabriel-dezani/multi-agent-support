from app.handoff.repository import HandoffRepository


class HumanEscalationAgent:
    """Creates a durable human-support case instead of only setting a flag."""

    def __init__(self, repository=None):
        self.repository = repository or HandoffRepository()

    @staticmethod
    def _summary(message: str, history: list[dict] | None, agent_results: list[dict] | None) -> str:
        parts: list[str] = []
        for row in (history or [])[-4:]:
            parts.append(f"{row.get('role')}: {row.get('content')}")
        if message:
            parts.append(f"user_current: {message}")
        for result in (agent_results or [])[-3:]:
            parts.append(f"{result.get('agent')}: {result.get('answer')}")
        return "\n".join(parts)[-4000:]

    def process(
        self,
        reason: str,
        request_id: str,
        *,
        user_id: str,
        conversation_id: str,
        message: str = "",
        history: list[dict] | None = None,
        agent_results: list[dict] | None = None,
    ):
        safe_reason = reason or "Necessidade de atendimento humano."
        try:
            record = self.repository.create(
                request_id=request_id,
                conversation_id=conversation_id,
                user_id=user_id,
                reason=safe_reason,
                summary=self._summary(message, history, agent_results),
            )
            handoff_id = record["handoff_id"]
            status = record["status"]
            answer = (
                "A solicitação foi colocada na fila de atendimento humano. "
                f"Protocolo: {handoff_id}. Status: {status}."
            )
            errors = []
        except Exception as exc:
            handoff_id = ""
            status = "failed"
            answer = (
                "O sistema identificou necessidade de atendimento humano, mas não conseguiu criar o caso automaticamente. "
                f"Use o request_id {request_id} para acompanhamento."
            )
            errors = [f"handoff_repository: {type(exc).__name__}"]

        result = {
            "answer": answer,
            "confidence": 0.0,
            "requires_human": True,
            "sources": [],
            "tools_used": [],
            "handoff_id": handoff_id,
            "handoff_status": status,
        }
        if errors:
            result["errors"] = errors
        return result
