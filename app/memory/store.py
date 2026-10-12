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
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages
                    (conversation_id, user_id, role, content, request_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, role, content, request_id),
            )

    def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
        request_id: str,
    ) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO conversation_messages
                    (conversation_id, user_id, role, content, request_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (conversation_id, user_id, "user", user_message, request_id),
                    (conversation_id, user_id, "assistant", assistant_message, request_id),
                ],
            )

    def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        limit = limit or get_settings().memory_max_messages
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, request_id, created_at
                FROM conversation_messages
                WHERE conversation_id = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, user_id, int(limit)),
            ).fetchall()
            history = [{key: row[key] for key in ("role", "content", "request_id", "created_at")}
                       for row in reversed(rows)]
            # A bounded window can contain only consecutive ellipses. Recover
            # ONE earlier topic from this exact user/session, without growing
            # the prompt window or concatenating unrelated old conversations.
            if rows and not contextual_user_anchor("E isso?", history):
                earlier = conn.execute(
                    "SELECT role,content FROM conversation_messages "
                    "WHERE conversation_id=? AND user_id=? AND role='user' AND id<? "
                    "ORDER BY id DESC LIMIT 100",
                    (conversation_id, user_id, rows[-1]["id"]),
                ).fetchall()
                anchor = contextual_user_anchor("E isso?", [dict(row) for row in reversed(earlier)])
                if anchor:
                    history[-1]["context_anchor"] = anchor
        return history

    def clear(self, conversation_id: str, user_id: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            return int(cursor.rowcount)
