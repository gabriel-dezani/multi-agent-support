"""Privacy boundary for ALL Tavily queries, regardless of planner decisions.

Never export a raw query that contains identifiers, customer/account context,
or conversational history. For known public subjects, reconstruct a narrow
independent query; otherwise fail closed for human review.
"""
import re
import unicodedata


def _normalized(text: str) -> str:
    text = unicodedata.normalize('NFD', text or '')
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn').lower()


_SENSITIVE = re.compile(
    r'@|\b(?:\d[. -]?){9,}\d\b|\b(?:cpf|cnpj|rg|senha|password|token|api[_ -]?key|'
    r'extrato|conta|account|meu saldo|my balance|meu terminal|my terminal|'
    r'minhas vendas|my sales|meu cliente|my customer|cartao|credit card|'
    r'repasse|payout|pix chave|chave pix|customer id|user_id)\b', re.I
)


def contains_private_context(message: str) -> bool:
    text = _normalized(message)
    # Detect formatted and unformatted Brazilian taxpayer ids, phone and card
    # numbers, emails, credentials and account requests. False positives are OK:
    # a denied search is preferable to exporting customer data.
    return bool(_SENSITIVE.search(text))


def safe_public_subquery(message: str) -> str | None:
    """Canonical public-only query extraction; NEVER copies user identifiers."""
    text = _normalized(message)
    if re.search(r'\b(euro|eur)\b', text) and re.search(r'\b(cotacao|cambio|exchange rate|rate)\b', text):
        return 'current EUR BRL exchange rate'
    if re.search(r'\b(dolar|dollar|usd)\b', text) and re.search(r'\b(cotacao|cambio|exchange rate|rate)\b', text):
        return 'current USD BRL exchange rate'
    if re.search(r'\b(weather|forecast|clima|previsao do tempo)\b', text):
        return 'weather forecast Brazil today'
    if re.search(r'\b(noticias|news|headlines)\b', text):
        return 'latest Brazil news'
    return None


def safe_public_search_query(message: str, *, mixed_private: bool = False) -> str | None:
    """Validate each external search even when the LLM chose *web_search only*."""
    canonical = safe_public_subquery(message)
    if canonical:
        return canonical
    if mixed_private or contains_private_context(message):
        return None
    # Allow ordinary public discovery but bound size and ban control/newlines.
    query = ' '.join(str(message).split())
    if len(query) > 300 or len(query) < 3 or re.search(r'[<>\x00-\x1f]', query):
        return canonical
    return query


def public_getnet_recovery_allowed(message: str) -> bool:
    text = _normalized(message)
    if contains_private_context(message) or re.search(r'\d', text):
        return False
    return bool(re.search(r'\b(getnet|pix|crediario|antecipacao|link de pagamento|get smart|get classica|payment link)\b', text))


def safe_official_getnet_query(message: str) -> str | None:
    """Never use untrusted original account text in a recovery search."""
    if not public_getnet_recovery_allowed(message):
        return None
    text = _normalized(message)
    for phrase in ('pix', 'crediario', 'antecipacao', 'link de pagamento', 'get smart', 'get classica'):
        if phrase in text:
            return f'site:site.getnet.com.br Getnet {phrase}'
    return 'site:site.getnet.com.br produtos Getnet'
