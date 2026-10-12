from app.memory.store import ConversationMemoryStore


def test_memory_persists_turns_and_isolates_users(tmp_path):
    store = ConversationMemoryStore(str(tmp_path / "state.db"))
    store.append_turn("conv-1", "user-a", "How does Pix work?", "Pix answer", "req-1")
    store.append_message("conv-1", "user-a", "human", "Human follow-up", "req-1")

    history = store.get_history("conv-1", "user-a")
    assert [row["role"] for row in history] == ["user", "assistant", "human"]
    assert history[0]["content"] == "How does Pix work?"
    assert store.get_history("conv-1", "user-b") == []


def test_memory_clear_removes_only_target_conversation(tmp_path):
    store = ConversationMemoryStore(str(tmp_path / "state.db"))
    store.append_turn("conv-a", "user-a", "q1", "a1", "req-1")
    store.append_turn("conv-b", "user-a", "q2", "a2", "req-2")
    assert store.clear("conv-a", "user-a") == 2
    assert store.get_history("conv-a", "user-a") == []
    assert len(store.get_history("conv-b", "user-a")) == 2
