import re
import unicodedata
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
        "venda", "sale", "sales", "pagamento", "payment",
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
        for term in terms:
            n = cls._normalize(term)
            if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text):
                return True
        return False

    def process(self, message, user_id):
        normalized = self._normalize(message)
        terminal = self._matches(normalized, self.TERMINAL_TERMS)
        sales = self._matches(normalized, self.SALES_TERMS)

        # Mixed support intents are unsafe to resolve with a single tool.
        if terminal and sales:
            return {
                "answer": "Sua solicitação envolve mais de um tipo de atendimento. Ela será encaminhada para um atendente humano.",
                "tools_used": [],
                "confidence": 0.0,
                "requires_human": True,
                "handoff_reason": "A mensagem combina suporte de terminal e dados de vendas.",
            }

        if not terminal and not sales:
            return {
                "answer": "Não consegui determinar com segurança qual consulta de suporte deve ser realizada. A solicitação será encaminhada para um atendente humano.",
                "tools_used": [],
                "confidence": 0.0,
                "requires_human": True,
                "handoff_reason": "Intenção de suporte insuficientemente específica para selecionar uma tool.",
            }

        use_terminal = terminal
        name = "get_terminal_status" if use_terminal else "get_sales_data"
        try:
            result = get_terminal_status(user_id, self.repository) if use_terminal else get_sales_data(user_id, self.repository)
        except Exception as exc:
            return {
                "answer": "Não foi possível consultar os dados de suporte. A solicitação será encaminhada para atendimento humano.",
                "tools_used": [name],
                "confidence": 0.0,
                "requires_human": True,
                "errors": [f"support_tool: {type(exc).__name__}"],
                "handoff_reason": "Falha controlada durante a execução da tool de suporte.",
            }
        if not result.ok:
            answer = "Cliente não encontrado." if result.error == "customer_not_found" else "Não foi possível consultar os dados. A solicitação será encaminhada para atendimento humano."
            return {
                "answer": answer,
                "tools_used": [name],
                "confidence": 0.2,
                "requires_human": True,
                "handoff_reason": "A consulta à tool de suporte não pôde ser concluída.",
            }

        data = result.data
        if use_terminal:
            answer = (
                f"Terminal {data.get('model')}: conexão {data.get('connection')} "
                f"e última sincronização {data.get('last_sync')}."
            )
        else:
            answer = (
                f"Venda com status {data.get('status')}, valor "
                f"R$ {data.get('amount', 0):.2f} e previsão de repasse em "
                f"{data.get('settlement_date')}."
            )
        return {
            "answer": answer,
            "tools_used": [name],
            "confidence": 0.95,
            "requires_human": False,
        }
