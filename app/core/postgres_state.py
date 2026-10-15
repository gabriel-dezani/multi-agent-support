"""Optional central PostgreSQL state for memory, handoffs and telemetry.

SQLite remains the zero-cost default. psycopg is imported lazily, so an offline
installation does not require a running server. All SQL values are parameterized;
connection strings and customer contents are never written to logs.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlsplit, parse_qs

from app.core.telemetry import TelemetryRepository


def connection_options(dsn, *, advisory=False):
    """Preserve trusted URI options (e.g. search_path) and append safety caps."""
    original = parse_qs(urlsplit(dsn).query, keep_blank_values=True).get('options', [''])[-1]
    bounds = ('-c statement_timeout=5000 -c lock_timeout=5000' if advisory else
              '-c statement_timeout=15000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=15000')
    return (original + ' ' + bounds).strip()


def _connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('PostgreSQL backend requires pip install "psycopg[binary]"') from exc
    if not dsn or not dsn.startswith(('postgresql://', 'postgres://')):
        raise ValueError('STATE_DATABASE_URL must use PostgreSQL')
    return psycopg.connect(dsn, connect_timeout=5,
        options=connection_options(dsn))


class PgCursor:
    def __init__(self, cursor, *, mapping=False):
        self._cursor = cursor
        self._mapping = mapping
        self.rowcount = cursor.rowcount

    def _one(self, row):
        if row is None:
            return None
        if self._mapping:
            return dict(zip([desc.name for desc in self._cursor.description], row))
        return row

    def fetchone(self):
        return self._one(self._cursor.fetchone())

    def fetchall(self):
        return [self._one(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class PgSession:
    """Small DB-API adapter for existing bounded, parameterized SQL statements."""
    row_factory = None

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, parameters=()):
        # Every application statement uses '?' placeholders, not '%' formatting.
        # SQL text is authored in our repository, never accepted from customers.
        if 'sqlite_master' in sql:
            sql = "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='handoffs'"
        cursor = self._connection.execute(sql.replace('?', '%s'), parameters)
        return PgCursor(cursor, mapping=self.row_factory is not None)

    def executemany(self, sql, parameters):
        cursor = self._connection.cursor()
        cursor.executemany(sql.replace('?', '%s'), parameters)
        return PgCursor(cursor)


@contextmanager
def pg_session(dsn):
    with _connect(dsn) as conn:
        # psycopg commits only on successful exit, otherwise rolls back.
        yield PgSession(conn)


class PostgresConversationMemoryStore:
    """Same public memory contract as ConversationMemoryStore; central DB."""

    def __init__(self, dsn):
        self.dsn = dsn
        self._init_db()

    def _init_db(self):
        with pg_session(self.dsn) as db:
            from app.core.distributed_lock import advisory_key
            db.execute('SELECT pg_advisory_xact_lock(?)', (advisory_key('schema','memory',namespace='migration'),))
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_messages (
                id BIGSERIAL PRIMARY KEY, conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL, role TEXT NOT NULL
                CHECK(role IN ('user','assistant','human')),
                content TEXT NOT NULL, request_id TEXT,
                created_at TEXT NOT NULL DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'))""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_conversation_messages ON conversation_messages(conversation_id,user_id,id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_conversation_retention ON conversation_messages(created_at)")
            from app.memory.topics import migrate_topics
            migrate_topics(db, postgres=True)

    def append_message(self, conversation_id, user_id, role, content, request_id=None):
        if role not in {'user', 'assistant', 'human'}:
            raise ValueError('invalid memory role')
        from app.memory.topics import write_topic
        with pg_session(self.dsn) as db:
            if role == 'user':
                from app.core.distributed_lock import advisory_key
                db.execute('SELECT pg_advisory_xact_lock(?)',
                           (advisory_key(user_id,conversation_id,namespace='memory-turn'),))
            db.execute("INSERT INTO conversation_messages(conversation_id,user_id,role,content,request_id,topic_anchor) VALUES (?,?,?,?,?,?)",
                       (conversation_id,user_id,role,content,request_id,
                        write_topic(db,conversation_id,user_id,content) if role == 'user' else None))

    def append_turn(self, conversation_id, user_id, user_message, assistant_message, request_id):
        from app.core.distributed_lock import advisory_key
        from app.memory.topics import write_topic
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError('append_turn requires a nonempty request_id')
        with pg_session(self.dsn) as db:
            # A transaction lock survives across application processes and is
            # released by commit/rollback, including a failed second insert.
            db.execute('SELECT pg_advisory_xact_lock(?)',
                       (advisory_key(user_id, conversation_id, namespace='memory-turn'),))
            existing = db.execute(
                "SELECT role,content FROM conversation_messages WHERE conversation_id=? "
                "AND user_id=? AND request_id=? AND role IN ('user','assistant') ORDER BY id",
                (conversation_id,user_id,request_id)).fetchall()
            if existing:
                if existing != [('user',user_message),('assistant',assistant_message)]:
                    raise ValueError('request_id conflicts with a persisted turn')
                return
            db.executemany("INSERT INTO conversation_messages(conversation_id,user_id,role,content,request_id,topic_anchor) VALUES (?,?,?,?,?,?)",
                           [(conversation_id,user_id,'user',user_message,request_id,
                             write_topic(db,conversation_id,user_id,user_message)),
                            (conversation_id,user_id,'assistant',assistant_message,request_id,None)])

    def get_history(self, conversation_id, user_id, limit=None, current_message=None):
        from app.core.config import get_settings
        from app.memory.store import attach_context_anchor
        from app.orchestration.context import is_contextual_followup
        from app.memory.topics import previous_topic, recall_terms, expose_resolved_topics
        limit = limit or get_settings().memory_max_messages
        with pg_session(self.dsn) as db:
            rows = db.execute("SELECT id,role,content,request_id,created_at,topic_anchor FROM conversation_messages "
                              "WHERE conversation_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                              (conversation_id,user_id,int(limit))).fetchall()
            history = [dict(zip(('id','role','content','request_id','created_at','topic_anchor'), row)) for row in reversed(rows)]
            expose_resolved_topics(history)
            previous = []
            if rows and (is_contextual_followup(current_message or '') or recall_terms(current_message)):
                before = rows[0][0] + 1 if recall_terms(current_message) else rows[-1][0]
                anchor = previous_topic(db,conversation_id,user_id,before,current_message)
                previous = [{'role':'user','content':anchor}] if anchor else []
            if recall_terms(current_message):
                if previous:
                    history[-1]['context_anchor'] = previous[0]['content']
                    history[-1]['topic_recalled'] = True
            else:
                attach_context_anchor(history,current_message,previous)
        return [{k:v for k,v in row.items() if k != 'id'} for row in history]

    def purge_expired(self, retention_days=None):
        from app.core.config import get_settings
        days = get_settings().memory_retention_days if retention_days is None else retention_days
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise ValueError('retention_days must be nonnegative')
        if not days:
            return 0
        with pg_session(self.dsn) as db:
            return db.execute("DELETE FROM conversation_messages WHERE created_at < "
                              "to_char((CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - (? * INTERVAL '1 day'), 'YYYY-MM-DD HH24:MI:SS')",
                              (days,)).rowcount

    def clear(self, conversation_id, user_id):
        with pg_session(self.dsn) as db:
            return db.execute("DELETE FROM conversation_messages WHERE conversation_id=? AND user_id=?",
                              (conversation_id,user_id)).rowcount


class PostgresHandoffRepository:
    """Atomic pending ticket deduplication via a partial unique constraint."""
    def __init__(self, dsn):
        self.dsn = dsn
        with pg_session(dsn) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS handoffs (
                handoff_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL, user_id TEXT NOT NULL,
                reason TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, resolved_at TEXT, resolution TEXT, resolved_by TEXT)""")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_handoff "
                       "ON handoffs(conversation_id,user_id) WHERE status='pending'")
            db.execute("CREATE INDEX IF NOT EXISTS idx_handoffs_status_created ON handoffs(status,created_at)")

    def create(self, *, request_id, conversation_id, user_id, reason, summary):
        key = f'handoff-{uuid4()}'
        created_at = datetime.now(timezone.utc).isoformat()
        with pg_session(self.dsn) as db:
            db.execute("""INSERT INTO handoffs(handoff_id,request_id,conversation_id,user_id,reason,summary,status,created_at)
                VALUES(?,?,?,?,?,?,'pending',?) ON CONFLICT (conversation_id,user_id) WHERE status='pending' DO NOTHING""",
                (key,request_id,conversation_id,user_id,reason,summary,created_at))
            db.row_factory = dict
            row = db.execute("SELECT * FROM handoffs WHERE conversation_id=? AND user_id=? AND status='pending'",
                             (conversation_id,user_id)).fetchone()
        if row is None:
            raise RuntimeError('Pending handoff transaction failed')
        return row

    def pending(self, conversation_id, user_id):
        with pg_session(self.dsn) as db:
            db.row_factory = dict
            return db.execute("SELECT * FROM handoffs WHERE conversation_id=? AND user_id=? AND status='pending'",
                              (conversation_id,user_id)).fetchone()

    def user_cases(self, conversation_id, user_id):
        with pg_session(self.dsn) as db:
            db.row_factory = dict
            return db.execute("SELECT handoff_id,status,reason,resolution,created_at,resolved_at "
                              "FROM handoffs WHERE conversation_id=? AND user_id=? ORDER BY created_at DESC",
                              (conversation_id,user_id)).fetchall()

    def get(self, handoff_id):
        with pg_session(self.dsn) as db:
            db.row_factory = dict
            return db.execute("SELECT * FROM handoffs WHERE handoff_id=?", (handoff_id,)).fetchone()

    def list(self, status='pending', limit=50):
        with pg_session(self.dsn) as db:
            db.row_factory = dict
            return db.execute("SELECT * FROM handoffs WHERE status=? ORDER BY created_at ASC LIMIT ?",
                              (status,int(limit))).fetchall()

    def resolve(self, handoff_id, *, resolution, resolved_by, append_memory=False):
        resolved_at = datetime.now(timezone.utc).isoformat()
        with pg_session(self.dsn) as db:
            changed = bool(db.execute("UPDATE handoffs SET status='resolved', resolved_at=?, resolution=?,resolved_by=? "
                                      "WHERE handoff_id=? AND status='pending'",
                                      (resolved_at,resolution,resolved_by,handoff_id)).rowcount)
            db.row_factory = dict
            row = db.execute("SELECT * FROM handoffs WHERE handoff_id=?", (handoff_id,)).fetchone()
            if changed and append_memory:
                db.execute("INSERT INTO conversation_messages(conversation_id,user_id,role,content,request_id) "
                           "VALUES(?,?,'human',?,?)",
                           (row['conversation_id'], row['user_id'], resolution, row['request_id']))
        if row is not None:
            row['_transitioned'] = changed
        return row


class PostgresTelemetryRepository(TelemetryRepository):
    """Share the existing schema-independent telemetry/aggregation semantics."""
    def __init__(self, dsn):
        self.dsn = dsn
        with pg_session(dsn) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS request_spans (
                request_id TEXT NOT NULL, seq INTEGER NOT NULL, agent TEXT NOT NULL,
                duration_ms DOUBLE PRECISION NOT NULL, status TEXT NOT NULL,
                details_json TEXT, PRIMARY KEY(request_id,seq))""")
            db.execute("""CREATE TABLE IF NOT EXISTS request_stats (
                request_id TEXT PRIMARY KEY, user_ref TEXT NOT NULL, route TEXT NOT NULL,
                latency_ms DOUBLE PRECISION NOT NULL, escalated INTEGER NOT NULL,
                degraded INTEGER NOT NULL, agents_count INTEGER NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd DOUBLE PRECISION,
                retrieval_hits INTEGER, retrieval_best_score DOUBLE PRECISION,
                created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'),
                session_ref TEXT, plan_json TEXT, routing_strategy TEXT,
                status_code INTEGER DEFAULT 200, error_type TEXT, usage_complete INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS user_feedback (
                request_id TEXT NOT NULL, user_ref TEXT NOT NULL, rating INTEGER NOT NULL,
                created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS'),
                PRIMARY KEY(request_id,user_ref))""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_request_stats_created_at ON request_stats(created_at)")

    @contextmanager
    def connect(self):
        with pg_session(self.dsn) as db:
            yield db
