"""Local bearer-token identities for the challenge; fail closed without configuration.

No external identity provider is needed, but user_id must be bound to a credential.
Credentials are demo-only; deploy behind TLS, secure vault and network controls.
"""
import hmac
import json
from datetime import datetime, timezone
from fastapi import Header, HTTPException
from app.core.config import get_settings


def resolve_identity(authorization: str | None = Header(default=None)) -> dict:
    raw = get_settings().api_credentials_json
    try:
        credentials = json.loads(raw)
        if not isinstance(credentials, dict):
            raise ValueError("not an object")
    except (TypeError, ValueError):
        raise HTTPException(status_code=503, detail="Credenciais da API inválidas.")
    if not credentials:
        raise HTTPException(status_code=503, detail="Autenticação local não configurada.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token Bearer obrigatório.")
    provided = authorization[7:]
    if not provided or not provided.isascii():
        raise HTTPException(status_code=401, detail="Token inválido.")
    # Don't short-circuit comparison based on token prefix or length.
    matched = None
    for token, subject in credentials.items():
        if isinstance(token, str) and token.isascii() and hmac.compare_digest(provided, token):
            matched = subject
    if not isinstance(matched, dict):
        raise HTTPException(status_code=401, detail="Token inválido.")
    user_id, role = matched.get("user_id"), matched.get("role")
    if not isinstance(user_id, str) or not user_id or role not in {"customer", "operator"}:
        raise HTTPException(status_code=401, detail="Credencial inválida.")
    if "expires_at" in matched:
        try:
            expiry = datetime.fromisoformat(matched["expires_at"])
            if expiry.tzinfo is None:
                raise ValueError("timezone required")
        except (TypeError, ValueError):
            raise HTTPException(status_code=503, detail="Validade da credencial não configurada corretamente.")
        if expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Credencial expirada.")
    return {"user_id": user_id, "role": role}


def assert_customer(identity: dict, claimed_user_id: str) -> None:
    if identity["role"] != "customer" or identity["user_id"] != claimed_user_id:
        raise HTTPException(status_code=403, detail="Identidade não autorizada para o usuário.")
