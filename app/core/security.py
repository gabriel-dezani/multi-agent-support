import hashlib
import secrets

from app.core.config import get_settings


def user_ref(user_id: str) -> str:
    """Return a stable pseudonymous reference suitable for logs."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


def operator_token_is_valid(provided: str) -> bool:
    """Validate the operator token with constant-time comparison.

    A blank configured token disables operator/debug endpoints entirely.
    """
    expected = get_settings().operator_token
    return bool(expected and provided and expected.isascii() and provided.isascii()
                and secrets.compare_digest(provided, expected))
