class HumanEscalationAgent:
    def process(self, reason: str, request_id: str):
        safe_reason = reason or "Necessidade de atendimento humano."
        return {
            "answer": f"Encaminhamento humano necessário. Use o request_id {request_id}. Motivo: {safe_reason}",
            "confidence": 0.0,
            "requires_human": True,
            "sources": [],
            "tools_used": [],
        }
