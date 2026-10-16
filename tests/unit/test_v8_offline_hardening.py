"""Free, deterministic V8 engineering regressions (no outbound API)."""
import pytest
from fastapi.testclient import TestClient
from app.evaluation.retrieval import metrics_at_k
from app.core.auth import authenticated_identity


def test_mrr_does_not_ignore_bad_source_before_a_real_hit():
    gold = ["https://site.getnet.com.br/pix/"]
    sources = ["http://insecure.example.com/pix", "https://site.getnet.com.br/pix/"]
    metrics = metrics_at_k(gold, sources, k=3)
    assert metrics["mrr"] == .5
    assert metrics["ndcg_at_k"] == pytest.approx(1 / 1.5849625007, abs=1e-4)
    assert metrics["hit_at_k"] == 1.0


def test_duplicate_retrieved_sources_do_not_inflate_recall():
    gold = ["https://site.getnet.com.br/pix", "https://site.getnet.com.br/link"]
    scores = metrics_at_k(gold, [gold[0], gold[0]], 2)
    assert scores["recall_at_k"] == .5
    assert scores["precision_at_k"] == .5


def test_missing_authorization_fails_closed(monkeypatch):
    from app.core import auth
    from types import SimpleNamespace
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        auth_mode="local", api_credentials_json='{"good":{"user_id":"a","role":"customer"}}'
    ))
    with pytest.raises(Exception) as exc:
        authenticated_identity(None)
    assert getattr(exc.value, "status_code", None) == 401


def test_authentication_requires_known_token(monkeypatch):
    from app.core import auth
    from fastapi.security import HTTPAuthorizationCredentials
    from types import SimpleNamespace
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        auth_mode="local", api_credentials_json='{"good":{"user_id":"a","role":"customer"}}'
    ))
    identity = authenticated_identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials="good"))
    assert identity == {"user_id": "a", "role": "customer"}
    with pytest.raises(Exception) as exc:
        authenticated_identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong"))
    assert getattr(exc.value, "status_code", None) == 401
