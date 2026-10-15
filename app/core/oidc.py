"""Opt-in corporate OIDC: pinned RS256, JWKS signature, issuer and audience.

Never read an unverified claim to select identity or permissions. Client IDs
remain tied to signed, verified claims, as in the demo token flow.
"""
from functools import lru_cache
from urllib.parse import urlsplit

from fastapi import HTTPException


def _verify_config(settings):
    issuer, audience, jwks = settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url
    try:
        source = urlsplit(issuer)
        provider = urlsplit(jwks)
        if (source.scheme != 'https' or provider.scheme != 'https' or not source.hostname
                or not provider.hostname or source.hostname != provider.hostname
                or source.username or source.password or provider.username or provider.password
                or source.port not in (None, 443) or provider.port not in (None, 443)
                or not audience or not settings.oidc_user_claim or not settings.oidc_role_claim):
            raise ValueError('invalid OIDC configuration')
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, detail='Configuração OIDC inválida.') from exc
    return issuer, audience, jwks


@lru_cache(maxsize=8)
def _jwks_client(url: str):
    import jwt
    # PyJWT caches JWKS keys; the HTTPS URL is admin-provided and validated.
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=300,
                           timeout=3)


def verify_oidc_token(authorization: str | None, settings) -> dict:
    issuer, audience, jwks = _verify_config(settings)
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, detail='Token Bearer obrigatório.')
    token = authorization[7:]
    if not token or len(token) > 8192 or not token.isascii():
        raise HTTPException(401, detail='Token inválido.')
    try:
        import jwt
        key = _jwks_client(jwks).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'],
                            issuer=issuer, audience=audience,
                            options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']},
                            leeway=30)
    except Exception as exc:
        # Do not leak whether JWKS, key material or a signed identity failed.
        raise HTTPException(401, detail='Token de identidade inválido.') from exc
    user_id = claims.get(settings.oidc_user_claim)
    roles = claims.get(settings.oidc_role_claim)
    if isinstance(roles, str):
        roles = [roles]
    if (not isinstance(user_id, str) or not 1 <= len(user_id) <= 100
            or not isinstance(roles, list) or not all(isinstance(x, str) for x in roles)):
        raise HTTPException(403, detail='Credencial sem identidade ou papel autorizado.')
    role = ('operator' if settings.oidc_operator_role in roles
            else 'customer' if settings.oidc_customer_role in roles else None)
    if not role:
        raise HTTPException(403, detail='Papel não autorizado.')
    return {'user_id': user_id, 'role': role}
