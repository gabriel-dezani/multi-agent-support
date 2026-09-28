import re
import unicodedata


class RouterAgent:
    """Deterministic intent router designed to be conservative and testable.

    It uses normalized phrase matching instead of raw substrings and returns
    human escalation for explicit human requests or genuinely conflicting
    high-signal intents.
    """

    SUPPORT = (
        "deposito", "deposit", "vendas de ontem", "yesterday's sales",
        "sales from yesterday", "payout", "settlement", "repasse",
        "recebimento", "internet", "conectar", "connect", "connection",
        "maquininha", "card machine", "terminal", "transacao recusada",
        "transaction declined", "declined transaction", "transaction decline",
        "erro na transacao", "error on the transaction", "problema com a maquina",
        "problem with the card machine", "venda recusada", "payment declined",
        "pagamento recusado", "payment was declined", "payment declined", "sale was declined", "help with a sale", "ajuda com uma venda", "ajuda com vendas", "suporte", "support",
        "nao consigo", "cannot", "can't", "cant",
    )
    CURRENT = (
        "previsao do tempo", "weather", "weather forecast", "forecast",
        "clima", "temperatura hoje", "temperatura tomorrow", "cotacao",
        "exchange rate", "cambio", "euro hoje", "today's euro", "euro exchange",
        "dolar hoje", "today's dollar", "dollar exchange", "noticias", "news",
        "hoje", "today", "agora", "now",
    )
    HUMAN = (
        "atendente", "atendimento humano", "falar com uma pessoa", "falar com humano",
        "human agent", "human support", "real person", "talk to a person",
        "speak to an agent", "call an agent",
    )

    REASON = {
        "customer_support": "A solicitação depende de dados ou suporte do cliente.",
        "web_search": "A pergunta solicita informação externa atual.",
        "human_escalation": "O cliente solicitou atendimento humano.",
        "knowledge": "A pergunta solicita conhecimento sobre produtos ou serviços.",
    }

    @staticmethod
    def normalize(text: str) -> str:
        text = unicodedata.normalize("NFD", text or "")
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = text.casefold()
        text = re.sub(r"[^\w\s']+", " ", text, flags=re.UNICODE)
        return " ".join(text.split())

    @staticmethod
    def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
        matches: list[str] = []
        for term in terms:
            normalized = RouterAgent.normalize(term)
            if not normalized:
                continue
            pattern = rf"(?<!\w){re.escape(normalized)}(?!\w)"
            if re.search(pattern, text):
                matches.append(normalized)
        return matches

    def route(self, message: str, user_id: str) -> dict[str, str]:
        del user_id
        normalized = self.normalize(message)
        human = self._matches(normalized, self.HUMAN)
        if human:
            return {"route": "human_escalation", "route_reason": self.REASON["human_escalation"]}

        support = self._matches(normalized, self.SUPPORT)
        current = self._matches(normalized, self.CURRENT)

        # A phrase with a concrete support intent wins over generic temporal
        # words such as "today". Current-information routing requires a
        # current-data signal beyond generic words.
        current_strong = [x for x in current if x not in {"hoje", "today", "agora", "now"}]

        if support and current_strong:
            return {
                "route": "human_escalation",
                "route_reason": "A solicitação combina intenções de suporte e informação atual e requer esclarecimento.",
            }
        if support:
            return {"route": "customer_support", "route_reason": self.REASON["customer_support"]}
        if current_strong:
            return {"route": "web_search", "route_reason": self.REASON["web_search"]}
        return {"route": "knowledge", "route_reason": self.REASON["knowledge"]}
