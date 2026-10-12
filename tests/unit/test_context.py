import pytest

from app.agents.router import RouterAgent
from app.memory.store import ConversationMemoryStore
from app.orchestration.context import contextual_user_anchor, is_contextual_followup


def test_followup_detector_is_conservative():
    assert is_contextual_followup("And what about yesterday?") is True
    assert is_contextual_followup("E isso no Pix?") is True
    assert is_contextual_followup("How does Payment Link work?") is False
    assert is_contextual_followup("") is False


@pytest.mark.parametrize("turns,expected", [
    (["Minhas vendas de ontem", "E hoje?"], "customer_support"),
    (["Minhas vendas de ontem", "E hoje?", "E quanto foi?"], "customer_support"),
    (["Minhas vendas de ontem", "E isso no Pix?", "E hoje?"], "knowledge"),
    (["Minha maquininha não conecta", "Como funciona o Pix?", "E isso?"], "knowledge"),
])
def test_consecutive_followups_keep_only_the_nearest_explicit_topic(turns, expected):
    history = [{"role": "user", "content": turn} for turn in turns]
    assert RouterAgent(enable_llm=False).route("E quanto foi?", "alice", history)["plan"] == [expected]


@pytest.mark.parametrize("message", [
    "E quanto foi?",
    "Quanto foi?",
    "E quanto deu?",
    "E quanto custou isso?",
    "E quantas foram?",
    "Qual foi o valor?",
    "E qual é o total?",
    "  E QUANTO FOI?!  ",
])
def test_amount_followups_reuse_the_previous_user_turn(message):
    history = [
        {"role": "user", "content": "Problema na maquininha"},
        {"role": "user", "content": "Minhas vendas de ontem"},
        {"role": "assistant", "content": "Informação sobre Pix"},
    ]
    assert is_contextual_followup(message)
    assert contextual_user_anchor(message, history) == "Minhas vendas de ontem"
    assert RouterAgent(enable_llm=False).route(message, "alice", history)["plan"] == [
        "customer_support"
    ]


@pytest.mark.parametrize("message", [
    "E quanto ao crediário?",
    "E quanto foi no Pix?",
    "Qual foi o valor do crediário?",
    "E quanto custou o produto Getnet?",
])
def test_amount_questions_with_explicit_subjects_do_not_borrow_history(message):
    history = [{"role": "user", "content": "Minhas vendas de ontem"}]
    assert not is_contextual_followup(message)
    assert contextual_user_anchor(message, history) == ""
    assert RouterAgent(enable_llm=False).route(message, "alice", history)["plan"] == [
        "knowledge"
    ]


@pytest.mark.parametrize("previous,message,expected", [
    ("Minhas vendas de ontem", "E quanto foi?", "customer_support"),
    ("Minhas vendas de ontem", "E hoje?", "customer_support"),
    ("Problema na maquininha", "E quanto ao crediário?", "knowledge"),
    ("Minhas vendas de ontem", "Como funciona o Pix?", "knowledge"),
    ("Minhas vendas de ontem", "E isso no Pix?", "knowledge"),
])
def test_contextual_routing_preserves_explicit_topic_changes(previous, message, expected):
    router = RouterAgent(enable_llm=False)
    first = router.route(previous, "alice")
    assert first["plan"] == ["customer_support"]
    history = [{"role": "user", "content": previous}]
    assert router.route(message, "alice", history)["plan"] == [expected]


@pytest.mark.parametrize("user_id,session_id,expected", [
    ("alice", "sales-session", "customer_support"),
    ("bob", "sales-session", "knowledge"),
    ("alice", "pix-session", "knowledge"),
    ("alice", "empty-session", "knowledge"),
])
def test_contextual_routing_uses_only_the_requested_user_and_session(
    tmp_path, user_id, session_id, expected
):
    store = ConversationMemoryStore(str(tmp_path / "context.db"))
    store.append_turn("sales-session", "alice", "Minhas vendas de ontem", "Vendas", "req-1")
    store.append_turn("sales-session", "bob", "Como funciona o Pix?", "Pix", "req-2")
    store.append_turn("pix-session", "alice", "Como funciona o Pix?", "Pix", "req-3")

    history = store.get_history(session_id, user_id)
    if expected == "knowledge":
        assert all(row["content"] != "Minhas vendas de ontem" for row in history)
    assert RouterAgent(enable_llm=False).route("E quanto foi?", user_id, history)["plan"] == [
        expected
    ]
