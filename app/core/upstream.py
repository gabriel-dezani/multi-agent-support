"""Typed, privacy-preserving classification for provider configuration failures.

Do not create customer support tickets for exhausted API credits, disabled
accounts, invalid service credentials or provider-wide rate limits. Those are
service incidents, not unanswered customer questions.
"""

class UpstreamUnavailable(RuntimeError):
    """Retryable/unavailable provider response; never expose raw SDK error."""


_PROVIDER_CODES = frozenset({
    'credit_balance_exhausted', 'insufficient_quota', 'invalid_api_key',
    'account_deactivated', 'rate_limit_exceeded', 'billing_hard_limit_reached',
})


def classify_provider_error(exc: BaseException) -> bool:
    """Classify SDK errors via machine-readable codes, never message matching.

    Unknown exceptions retain the existing safe fallback behavior. Do not log
    exception messages, which may contain private request details.
    """
    codes = [getattr(exc, 'code', None), getattr(exc, 'type', None)]
    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        codes.extend([body.get('code'), body.get('type')])
        nested = body.get('error')
        if isinstance(nested, dict):
            codes.extend([nested.get('code'), nested.get('type')])
    return any(isinstance(code, str) and code in _PROVIDER_CODES for code in codes)
