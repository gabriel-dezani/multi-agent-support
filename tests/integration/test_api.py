import json

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("structlog")

from fastapi.testclient import TestClient
from app.core import auth
from app.core.config import Settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def customer_auth(monkeypatch):
    settings = Settings(
        _env_file=None,
        api_credentials_json=json.dumps({
            "test-customer-token": {"user_id": "cliente1988", "role": "customer"}
        }),
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    return {"Authorization": "Bearer test-customer-token"}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_empty_message(customer_auth):
    response = client.post(
        "/chat", headers=customer_auth,
        json={"message": "", "user_id": "cliente1988"},
    )
    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "message"] and error["type"] == "string_too_short"
        for error in response.json()["detail"]
    )


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer invalid-token"},
    {"Authorization": "test-customer-token"},
    {"Authorization": "Bearer "},
])
def test_chat_requires_valid_authentication(customer_auth, headers):
    response = client.post(
        "/chat", headers=headers,
        json={"message": "hello", "user_id": "cliente1988"},
    )
    assert response.status_code == 401


def test_metrics_operator_only():
    response = client.get("/metrics")
    assert response.status_code in (403, 503)
