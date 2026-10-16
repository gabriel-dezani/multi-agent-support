"""Lightweight local readiness without contacting paid or external providers."""
import sqlite3
from contextlib import closing
from pathlib import Path


def validate_deployment(settings):
    """Production cannot silently start with challenge/demo authentication."""
    # Prevent a false claim of horizontal scaling. Central SQL state is needed
    # but does not make the embedded Chroma vector index multi-writer safe.
    if getattr(settings, 'replicas', 1) > 1:
        if getattr(settings, 'state_backend', 'sqlite') != 'postgres':
            raise RuntimeError('Multiple replicas require PostgreSQL state backend')
        raise RuntimeError('Multiple replicas also require an external/shared vector service; local Chroma is not multi-writer safe')
    if getattr(settings, 'state_backend', 'sqlite') == 'postgres':
        if not getattr(settings, 'state_database_url', '').startswith(('postgresql://', 'postgres://')):
            raise RuntimeError('PostgreSQL state backend requires STATE_DATABASE_URL')
    if settings.app_env != 'production':
        return
    if settings.auth_mode != 'oidc':
        raise RuntimeError('Production requires AUTH_MODE=oidc')
    if not (settings.oidc_jwks_url and settings.oidc_issuer and settings.oidc_audience):
        raise RuntimeError('Production OIDC settings are incomplete')
    if settings.rag_verifier_mode != 'llm':
        raise RuntimeError('Production requires RAG_VERIFIER_MODE=llm')
    if not settings.otlp_endpoint:
        raise RuntimeError('Production requires an external OTLP tracing endpoint')
    from app.core.oidc import _verify_config
    from app.core.observability import validate_otlp_url
    _verify_config(settings)
    validate_otlp_url(settings.otlp_endpoint, settings.app_env)


def check_readiness(settings):
    if getattr(settings, 'state_backend', 'sqlite') == 'postgres':
        # Local Chroma is still a required index; the SQL probe is deliberately
        # read-only and must never create missing schema implicitly.
        if not Path(settings.vector_store_path).is_dir():
            return False
        try:
            from app.core.postgres_state import pg_session
            with pg_session(settings.state_database_url) as db:
                rows = db.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=current_schema() "
                    "AND table_name IN ('conversation_messages','handoffs','request_stats','request_spans','user_feedback')"
                ).fetchall()
                if {row[0] for row in rows} != {
                    'conversation_messages','handoffs','request_stats','request_spans','user_feedback'
                }:
                    return False
                db.execute('SELECT topic_anchor FROM conversation_messages LIMIT 0')
                return db.execute('SHOW transaction_read_only').fetchone()[0] == 'off'
        except Exception:
            return False
    path = Path(settings.state_db_path)
    try:
        if not path.parent.is_dir() or not Path(settings.vector_store_path).is_dir():
            return False
        # mode=rw refuses to create an absent database. A short reserved-lock
        # transaction verifies write capability without changing the schema.
        # The probe never writes customer data or creates tables.
        with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=1)) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('conversation_messages','handoffs','request_stats')")}
            if tables != {'conversation_messages','handoffs','request_stats'}:
                return False
            conn.execute('BEGIN IMMEDIATE')
            conn.rollback()
        return True
    except (sqlite3.Error, OSError):
        return False
