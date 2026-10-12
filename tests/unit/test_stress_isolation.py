"""Concurrent DB operations using real SQLite, not a database mock."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.handoff.repository import HandoffRepository
from app.memory.store import ConversationMemoryStore


def test_80_concurrent_escalations_have_one_pending_ticket(tmp_path):
    repo = HandoffRepository(str(tmp_path / "concurrent.db"))

    def make(n):
        return repo.create(request_id=str(uuid4()), conversation_id="same-session",
                           user_id="same-user", reason="needs human", summary=f"summary {n}")

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(make, range(80)))
    assert len({r["handoff_id"] for r in results}) == 1
    assert len(repo.list("pending")) == 1


def test_80_concurrent_operator_resolutions_are_exactly_once(tmp_path):
    path = str(tmp_path / "atomic.db")
    memory = ConversationMemoryStore(path)
    repo = HandoffRepository(path)
    ticket = repo.create(request_id="req-123", conversation_id="conversation",
                         user_id="alice", reason="help", summary="summary")

    def resolve(n):
        return repo.resolve(ticket["handoff_id"], resolution=f"answer {n}",
                            resolved_by="trusted-operator", append_memory=True)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(resolve, range(80)))
    assert sum(1 for r in results if r["_transitioned"]) == 1
    assert all(r["status"] == "resolved" for r in results)
    history = memory.get_history("conversation", "alice")
    assert len(history) == 1 and history[0]["role"] == "human"
    assert history[0]["content"] == repo.get(ticket["handoff_id"])["resolution"]


def test_30_concurrent_users_in_shared_conversation_never_mix_history(tmp_path):
    memory = ConversationMemoryStore(str(tmp_path / "tenants.db"))

    def write_user(n):
        user = f"user-{n:03d}"
        for turn in range(6):
            memory.append_turn("shared-conversation-id", user, f"question:{n}:{turn}",
                               f"answer:{n}:{turn}", f"req:{n}:{turn}")
        return user

    with ThreadPoolExecutor(max_workers=12) as pool:
        users = list(pool.map(write_user, range(30)))
    for n, user in enumerate(users):
        history = memory.get_history("shared-conversation-id", user, limit=30)
        assert len(history) == 12
        assert all(f":{n}:" in entry["content"] for entry in history)
        assert history[0]["role"] == "user" and history[-1]["role"] == "assistant"
