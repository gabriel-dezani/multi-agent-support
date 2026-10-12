import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings


class HandoffRepository:
    """Durable human-support queue used by the HumanEscalationAgent."""

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
                CREATE TABLE IF NOT EXISTS handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution TEXT,
                    resolved_by TEXT
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_handoff "
                "ON handoffs(conversation_id, user_id) WHERE status = 'pending'"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_handoffs_status_created "
                "ON handoffs(status, created_at)"
            )

    def create(
        self,
        *,
        request_id: str,
        conversation_id: str,
        user_id: str,
        reason: str,
        summary: str,
    ) -> dict:
        handoff_id = f"handoff-{uuid4()}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM handoffs WHERE conversation_id=? AND user_id=? AND status='pending'",
                (conversation_id, user_id),
            ).fetchone()
            if existing:
                return dict(existing)
            conn.execute(
                """INSERT INTO handoffs (
                    handoff_id, request_id, conversation_id, user_id,
                    reason, summary, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (handoff_id, request_id, conversation_id, user_id, reason, summary, created_at),
            )
        return self.get(handoff_id)

    def pending(self, conversation_id: str, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM handoffs WHERE conversation_id=? AND user_id=? AND status='pending'",
                (conversation_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def user_cases(self, conversation_id: str, user_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT handoff_id, status, reason, resolution, created_at, resolved_at "
                "FROM handoffs WHERE conversation_id=? AND user_id=? ORDER BY created_at DESC",
                (conversation_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, handoff_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM handoffs WHERE handoff_id = ?",
                (handoff_id,),
            ).fetchone()
        return dict(row) if row else None

    def list(self, status: str = "pending", limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM handoffs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (status, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve(self, handoff_id: str, *, resolution: str, resolved_by: str, append_memory: bool = False) -> dict | None:
        resolved_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE handoffs
                SET status = 'resolved', resolved_at = ?, resolution = ?, resolved_by = ?
                WHERE handoff_id = ? AND status = 'pending'
                """,
                (resolved_at, resolution, resolved_by, handoff_id),
            )
            changed = bool(cursor.rowcount)
            if changed and append_memory:
                row = conn.execute(
                    "SELECT conversation_id, user_id, request_id FROM handoffs WHERE handoff_id=?",
                    (handoff_id,),
                ).fetchone()
                conn.execute(
                    "INSERT INTO conversation_messages(conversation_id,user_id,role,content,request_id) "
                    "VALUES(?,?,'human',?,?)",
                    (row["conversation_id"], row["user_id"], resolution, row["request_id"]),
                )
        record = self.get(handoff_id)
        if record is not None:
            record["_transitioned"] = changed
        return record
