import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from app.core.config import get_settings
from app.orchestration.context import contextual_user_anchor


class ConversationMemoryStore:
    """Small durable conversation memory backed by SQLite.

    A conversation is isolated by both conversation_id and user_id. This keeps
    the challenge self-contained while demonstrating actual multi-turn state
    across independent HTTP requests and process restarts.
    """

    def __init__(self, path: str | None = None):
        self.path = Path(path or get_settings().state_db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        # sqlite3.Connection.__exit__ commits/rolls back but does NOT close.
        # Explicit closure prevents descriptor leaks in sustained API traffic.
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant','human')),
                    content TEXT NOT NULL,
                    request_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_messages "
                "ON conversation_messages(conversation_id, user_id, id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_retention "
                         "ON conversation_messages(created_at)")
            from app.memory.topics import migrate_topics
            migrate_topics(conn)

    def append_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        request_id: str | None = None,
    ) -> None:
        if role not in {"user", "assistant", "human"}:
            raise ValueError("invalid memory role")
        from app.memory.topics import write_topic
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(
                """
                INSERT INTO conversation_messages
                    (conversation_id, user_id, role, content, request_id, topic_anchor)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, role, content, request_id,
                 write_topic(conn,conversation_id,user_id,content) if role == 'user' else None),
            )

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
        request_id: str,
    ) -> None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("append_turn requires a nonempty request_id")
        from app.memory.topics import write_topic
        with self._connect() as conn:
            # Serialize check + insert across independent SQLite processes.
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT role,content FROM conversation_messages WHERE conversation_id=? "
                "AND user_id=? AND request_id=? AND role IN ('user','assistant') ORDER BY id",
                (conversation_id, user_id, request_id),
            ).fetchall()
            if existing:
                if [tuple(row) for row in existing] != [('user', user_message), ('assistant', assistant_message)]:
                    raise ValueError("request_id conflicts with a persisted turn")
                return
            conn.executemany(
                """
                INSERT INTO conversation_messages
                    (conversation_id, user_id, role, content, request_id, topic_anchor)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (conversation_id, user_id, "user", user_message, request_id,
                     write_topic(conn,conversation_id,user_id,user_message)),
                    (conversation_id, user_id, "assistant", assistant_message, request_id, None),
                ],
            )

    def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int | None = None,
        current_message: str | None = None,
    ) -> list[dict[str, str]]:
        """Bound the prompt window; only retrieve an older topic for a true follow-up.

        This optional current_message lets the caller distinguish a new topic
        from an elliptical question. Legacy callers retain their same history
        shape but no longer trigger an unnecessary search for old subjects.
        """
        from app.orchestration.context import is_contextual_followup
        from app.memory.topics import previous_topic, recall_terms, expose_resolved_topics
        limit = limit or get_settings().memory_max_messages
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, role, content, request_id, created_at, topic_anchor "
                "FROM conversation_messages WHERE conversation_id=? AND user_id=? "
                "ORDER BY id DESC LIMIT ?",
                (conversation_id, user_id, int(limit)),
            ).fetchall()
            history = [dict(row) for row in reversed(rows)]
            expose_resolved_topics(history)
            previous = []
            if rows and (is_contextual_followup(current_message or '') or recall_terms(current_message)):
                before = rows[0]['id'] + 1 if recall_terms(current_message) else rows[-1]['id']
                anchor = previous_topic(conn, conversation_id,user_id,before,current_message)
                previous = [{'role':'user','content':anchor}] if anchor else []
            if recall_terms(current_message):
                if previous:
                    history[-1]['context_anchor'] = previous[0]['content']
                    history[-1]['topic_recalled'] = True
            else:
                attach_context_anchor(history,current_message,previous)
        return [{key: row[key] for key in ('role','content','request_id','created_at', 'context_anchor','topic_recalled','resolved_topic')
                 if key in row} for row in history]

    def purge_expired(self, retention_days: int | None = None) -> int:
        """Optional, atomic TTL cleanup; safe across users and process restarts.

        The retention policy applies to conversation_messages only. Handoffs and
        audit records need their own corporate retention/legal-hold policy.
        """
        days = (get_settings().memory_retention_days if retention_days is None
                else retention_days)
        if not isinstance(days, int) or days < 0:
            raise ValueError("retention_days must be nonnegative")
        if days == 0:
            return 0
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_messages "
                "WHERE created_at < datetime('now', ?)", (f'-{days} days',)
            )
            return int(cursor.rowcount)

    def clear(self, conversation_id: str, user_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            return int(cursor.rowcount)


def attach_context_anchor(history: list[dict], current_message: str | None,
                          earlier_user_turns: list[dict]) -> None:
    """Attach one bounded prior explicit topic only for elliptical follow-ups.

    Existing explicit topics in the prompt window always win; an unrelated
    previous topic cannot be resurrected when the new question is explicit.
    """
    from app.orchestration.context import is_contextual_followup
    if not history or not is_contextual_followup(current_message or ''):
        return
    if contextual_user_anchor(current_message, history):
        return
    anchor = contextual_user_anchor(current_message, earlier_user_turns)
    if anchor:
        history[-1]['context_anchor'] = anchor
