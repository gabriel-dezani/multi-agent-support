"""Customer-support tools only see the authenticated user_id supplied by the API.

No LLM decides tool arguments. Independent terminal and sales requests can
both execute; a tool failure preserves successful evidence and creates a
human handoff for the unresolved portion.
"""
from time import perf_counter
import re
import unicodedata

from app.orchestration.context import contextual_user_anchor
from app.repositories.customer_repository import CustomerRepository
from app.tools.sales import get_sales_data
from app.tools.terminal import get_terminal_status


class CustomerSupportAgent:
    TERMINAL_TERMS = (
        "maquininha", "card machine", "terminal", "internet", "conectar",
        "connect", "connection", "transacao recusada", "transaction declined",
        "declined transaction", "transaction decline", "erro na transacao",
        "error on the transaction", "problema com a maquina", "problem with the card machine",
    )
    SALES_TERMS = (
        "deposito", "deposit", "vendas de ontem", "yesterday's sales",
        "sales from yesterday", "payout", "settlement", "repasse", "recebimento",
        "venda", "vendas", "sale", "sales", "pagamento", "payment",
    )

    def __init__(self, repository=None):
        self.repository = repository or CustomerRepository()

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFD", text or "")
        text = "".join(c for c in text if unicodedata.category(c) != "Mn").casefold()
        return " ".join(text.split())

    @classmethod
    def _matches(cls, text: str, terms: tuple[str, ...]) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(cls._normalize(term))}(?!\w)", text)
            for term in terms
        )

    def process(self, message, user_id, history=None):
        explicit_topic = (self._matches(self._normalize(message), self.TERMINAL_TERMS) or
                          self._matches(self._normalize(message), self.SALES_TERMS))
        recent_user = "" if explicit_topic else contextual_user_anchor(message, history)
        normalized = self._normalize(f"{recent_user} {message}".strip())
        selected = []
        if self._matches(normalized, self.TERMINAL_TERMS):
            selected.append(("get_terminal_status", get_terminal_status))
        if self._matches(normalized, self.SALES_TERMS):
            selected.append(("get_sales_data", get_sales_data))
        if not selected:
            return {
                "answer": "Não consegui identificar uma consulta de suporte segura. Vou encaminhar para um atendente.",
                "tools_used": [], "confidence": 0.0, "requires_human": True,
                "handoff_reason": "Nenhuma ferramenta de suporte foi identificada com segurança.",
            }

        answers, errors, spans = [], [], []
        for name, tool in selected:
            started = perf_counter()
            try:
                result = tool(user_id, self.repository)
                if not result.ok:
                    errors.append(f"{name}: {result.error or 'unavailable'}")
                    status = "unavailable"
                else:
                    data = result.data
                    if name == "get_terminal_status":
                        answers.append(
                            f"[Dados demonstrativos] Terminal {data.get('model')}: conexão {data.get('connection')} "
                            f"e última sincronização {data.get('last_sync')}."
                        )
                    else:
                        answers.append(
                            f"[Dados demonstrativos] Venda registrada no exemplo com status {data.get('status')}, valor "
                            f"R$ {data.get('amount', 0):.2f} e previsão de repasse em "
                            f"{data.get('settlement_date')}."
                        )
                    status = "ok"
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}")
                status = "error"
            spans.append({
                "agent": "tool:" + name,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "status": status,
            })

        missing = bool(errors)
        partial_answer = "\n".join(answers) if missing else ""
        if missing:
            answers.append("Uma ou mais consultas não puderam ser concluídas; vou encaminhar a parte pendente ao atendimento humano.")
        return {
            "answer": "\n".join(answers),
            "partial_answer": partial_answer,
            "tools_used": [name for name, _ in selected],
            "tool_spans": spans,
            "confidence": 0.95 if not missing else (0.2 if not answers[:-1] else 0.5),
            "requires_human": missing,
            "handoff_reason": "Falha em ferramentas de suporte: " + ", ".join(errors) if missing else "",
            "errors": errors,
        }
