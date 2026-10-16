from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from app.core.oidc import verify_oidc_token
from app.core.auth import resolve_identity


def settings(**changes):
    values = dict(auth_mode='oidc', oidc_issuer='https://identity.example.net/',
                  oidc_jwks_url='https://identity.example.net/keys',
                  oidc_audience='getnet-challenge', oidc_user_claim='sub',
                  oidc_role_claim='roles', oidc_operator_role='operator',
                  oidc_customer_role='customer')
    return SimpleNamespace(**(values | changes))


def test_oidc_rejects_non_https_and_foreign_jwks_before_network():
    for url in ('http://identity.example.net/keys', 'https://evil.example/keys',
                'https://identity.example.net:8443/keys'):
        with pytest.raises(HTTPException) as exc:
            verify_oidc_token('Bearer aaa.bbb.ccc', settings(oidc_jwks_url=url))
        assert exc.value.status_code == 503


def test_oidc_signed_claims_determine_customer_identity(monkeypatch):
    import jwt
    client = Mock()
    client.get_signing_key_from_jwt.return_value.key = 'public-key'
    monkeypatch.setattr('app.core.oidc._jwks_client', lambda url: client)
    calls = []
    def decode(token, key, **options):
        calls.append(options)
        return {'sub': 'cliente1988', 'roles': ['customer']}
    monkeypatch.setattr(jwt, 'decode', decode)
    assert verify_oidc_token('Bearer header.payload.signature', settings()) == {
        'user_id': 'cliente1988', 'role': 'customer'}
    assert calls[0]['algorithms'] == ['RS256']
    assert calls[0]['issuer'] == 'https://identity.example.net/'
    assert calls[0]['audience'] == 'getnet-challenge'
    assert 'exp' in calls[0]['options']['require']


def test_oidc_rejects_unsigned_identity_and_missing_roles(monkeypatch):
    import jwt
    client = Mock()
    client.get_signing_key_from_jwt.return_value.key = 'public-key'
    monkeypatch.setattr('app.core.oidc._jwks_client', lambda url: client)
    monkeypatch.setattr(jwt, 'decode', lambda *_args, **_kwargs: {'sub':'user'})
    with pytest.raises(HTTPException) as exc:
        verify_oidc_token('Bearer a.b.c', settings())
    assert exc.value.status_code == 403
    monkeypatch.setattr(jwt, 'decode', lambda *_args, **_kwargs: (_ for _ in ()).throw(jwt.InvalidSignatureError()))
    with pytest.raises(HTTPException) as exc:
        verify_oidc_token('Bearer a.b.c', settings())
    assert exc.value.status_code == 401


def test_oidc_mode_cannot_fall_back_to_local_tokens(monkeypatch):
    monkeypatch.setattr('app.core.auth.get_settings', lambda: settings())
    with pytest.raises(HTTPException) as exc:
        resolve_identity('Bearer demo-customer-token')
    assert exc.value.status_code == 401
