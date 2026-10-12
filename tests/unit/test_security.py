from types import SimpleNamespace

import app.core.security as security


def test_user_ref_is_stable_and_does_not_expose_raw_identifier():
    raw = "cliente1988"
    ref = security.user_ref(raw)
    assert ref == security.user_ref(raw)
    assert raw not in ref
    assert len(ref) == 12


def test_operator_token_validation_is_constant_contract(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(operator_token="secret-token"))
    assert security.operator_token_is_valid("secret-token") is True
    assert security.operator_token_is_valid("wrong") is False
    assert security.operator_token_is_valid("") is False


def test_blank_operator_token_disables_operator_access(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(operator_token=""))
    assert security.operator_token_is_valid("anything") is False
