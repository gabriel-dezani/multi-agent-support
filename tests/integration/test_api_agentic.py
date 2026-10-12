from types import SimpleNamespace

import pytest
import json

pytest.importorskip("langgraph")
pytest.importorskip("structlog")

from fastapi.testclient import TestClient

import app.api.routes as routes
import app.core.security as security
from app.handoff.repository import HandoffRepository
from app.main import app
from app.memory.store import ConversationMemoryStore
from app.core.config import get_settings
from app.core.telemetry import TelemetryRepository


class FakeGraph:
    async def ainvoke(self, state):
        history_size = len(state.get("history", []))
        return {
            **state,
            "route": "knowledge",
            "plan": ["knowledge", "customer_support"],
            "agent": "synthesis",
            "agents_used": ["knowledge", "customer_support", "synthesis"],
            "route_reason": "fake multi-agent plan",
            "answer": f"history={history_size}",
            "confidence": 0.9,
            "requires_human": False,
            "routing_strategy": "test",
            "routing_confidence": 1.0,
            "sources": ["https://example.com/getnet"],
            "tools_used": ["get_sales_data"],
            "errors": [],
        }


class BlockedGraph:
    async def ainvoke(self, state):
        return {
            **state,
            "route": "blocked",
            "plan": [],
            "agent": "blocked",
            "agents_used": ["blocked"],
            "route_reason": "blocked",
            "answer": "Não posso atender a essa solicitação.",
            "confidence": 1.0,
            "requires_human": False,
            "routing_strategy": "guardrail",
            "routing_confidence": 1.0,
            "sources": [],
            "tools_used": [],
            "errors": [],
        }


def _configure_state(monkeypatch, tmp_path, graph):
    monkeypatch.setenv("API_CREDENTIALS_JSON", json.dumps({"alice-token": {"user_id": "cliente1988", "role": "customer"}}))
    get_settings.cache_clear()
    monkeypatch.setattr(routes, "_telemetry", TelemetryRepository(str(tmp_path / "telemetry.db")))
    memory = ConversationMemoryStore(str(tmp_path / "support.db"))
    handoffs = HandoffRepository(str(tmp_path / "support.db"))
    monkeypatch.setattr(routes, "_graph", graph)
    monkeypatch.setattr(routes, "_memory", memory)
    monkeypatch.setattr(routes, "_handoffs", handoffs)
    return memory, handoffs


def _configure_operator(monkeypatch, token="operator-secret"):
    settings = SimpleNamespace(operator_token=token)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(security, "get_settings", lambda: settings)


def test_chat_reuses_persisted_history_and_exposes_multi_agent_trace(monkeypatch, tmp_path):
    memory, _ = _configure_state(monkeypatch, tmp_path, FakeGraph())
    client = TestClient(app)

    first = client.post("/chat", headers={"Authorization": "Bearer alice-token"}, json={"message": "first", "user_id": "cliente1988"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["answer"] == "history=0"
    assert first_body["agents_used"] == ["knowledge", "customer_support", "synthesis"]

    second = client.post(
        "/chat",
        headers={"Authorization": "Bearer alice-token"},
        json={
            "message": "And now?",
            "user_id": "cliente1988",
            "conversation_id": first_body["conversation_id"],
        },
    )
    assert second.status_code == 200
    assert second.json()["answer"] == "history=2"
    assert len(memory.get_history(first_body["conversation_id"], "cliente1988")) == 4


def test_blocked_prompt_is_not_persisted(monkeypatch, tmp_path):
    memory, _ = _configure_state(monkeypatch, tmp_path, BlockedGraph())
    client = TestClient(app)
    response = client.post("/chat", headers={"Authorization": "Bearer alice-token"}, json={"message": "malicious", "user_id": "cliente1988"})
    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "blocked"
    assert memory.get_history(body["conversation_id"], "cliente1988") == []


def test_conversation_history_requires_operator_token(monkeypatch, tmp_path):
    memory, _ = _configure_state(monkeypatch, tmp_path, FakeGraph())
    _configure_operator(monkeypatch)
    memory.append_turn("conv-1", "cliente1988", "hello", "answer", "req-1")
    client = TestClient(app)

    denied = client.get("/conversations/conv-1", params={"user_id": "cliente1988"})
    assert denied.status_code == 403

    allowed = client.get(
        "/conversations/conv-1",
        params={"user_id": "cliente1988"},
        headers={"X-Operator-Token": "operator-secret"},
    )
    assert allowed.status_code == 200
    assert len(allowed.json()["messages"]) == 2


def test_handoff_resolution_requires_operator_and_returns_to_memory(monkeypatch, tmp_path):
    memory, handoffs = _configure_state(monkeypatch, tmp_path, FakeGraph())
    _configure_operator(monkeypatch)
    record = handoffs.create(
        request_id="req-1",
        conversation_id="conv-1",
        user_id="cliente1988",
        reason="needs human",
        summary="summary",
    )
    client = TestClient(app)

    denied = client.post(
        f"/handoffs/{record['handoff_id']}/resolve",
        json={"resolution": "done", "resolved_by": "operator-1"},
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/handoffs/{record['handoff_id']}/resolve",
        json={"resolution": "done", "resolved_by": "operator-1"},
        headers={"X-Operator-Token": "operator-secret"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "resolved"
    history = memory.get_history("conv-1", "cliente1988")
    assert history[-1]["role"] == "human"
    assert history[-1]["content"] == "done"
