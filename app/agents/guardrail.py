import re
import unicodedata


class GuardrailAgent:
    """Lightweight input guardrail for common prompt-injection patterns.

    This is intentionally deterministic and fail-closed for explicit attempts
    to obtain hidden instructions or override the application's instructions.
    It is not presented as a complete security boundary.
    """

    PATTERNS = (
        r"\bignore\b.{0,80}\b(previous|prior|earlier)\b.{0,40}\b(instruction|instructions|prompt|rules)\b",
        r"\bdisregard\b.{0,80}\b(system|developer|previous|prior)\b.{0,40}\b(instruction|instructions|message|prompt)\b",
        r"\bforget\b.{0,50}\b(previous|prior|above)\b.{0,30}\b(instruction|instructions)\b",
        r"\b(show|reveal|print|display|give me|tell me)\b.{0,80}\b(system|developer|hidden|internal)\b.{0,40}\b(prompt|instructions?|message)\b",
        r"\b(show|reveal|print|display|give me|tell me)\b.{0,50}\b(my|your|the|these|those|hidden|internal)?\s*(prompt|instructions?|system message)\b",
        r"\b(mostre|revele|exiba|me mostre|me diga|diga)\b.{0,80}\b(prompt|instrucoes|mensagem|comandos)\b.{0,50}\b(sistema|system|developer|desenvolvedor|ocult[oa]|intern[oa]s?)\b",
        r"\b(mostre|revele|exiba|me mostre|me diga|diga)\b.{0,50}\b(suas|seus|as|os)?\s*(instrucoes|comandos|regras)\b.{0,30}\b(intern[oa]s?|ocult[oa]s?|sistema|system)\b",
        r"\b(ignore|disregard|bypass|override|follow)\b.{0,50}\b(system|developer|safety|guardrail)\b.{0,50}\b(instruction|instructions|rule|rules)\b",
        r"\bjailbreak\b",
        r"\bprompt\s*injection\b",
        r"\bact\s+as\s+(the\s+)?(system|developer|administrator)\b",
        r"\b(atue|aja)\s+como\s+(o\s+)?(sistema|desenvolvedor|administrador)\b",
    )

    @staticmethod
    def normalize(text: str) -> str:
        text = unicodedata.normalize("NFD", text or "")
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        return " ".join(text.casefold().split())

    def validate(self, message: str) -> dict[str, str | bool]:
        normalized = self.normalize(message)
        blocked = any(re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL) for pattern in self.PATTERNS)
        return {
            "allowed": not blocked,
            "message": "Não posso atender a essa solicitação." if blocked else "",
        }
