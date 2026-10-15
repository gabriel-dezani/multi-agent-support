"""Cross-replica session lock backed by PostgreSQL advisory locks.

Use a distinct scoped key for each authenticated customer + conversation.
The lock is owned by a dedicated DB connection, held until the HTTP request
finishes, and released even after cancellation or an upstream timeout.
"""
import asyncio
import hashlib
from contextlib import asynccontextmanager
from time import monotonic


def advisory_key(customer: str, conversation: str, *, namespace: str = '') -> int:
    payload = f'{len(customer)}:{customer}{len(conversation)}:{conversation}'.encode('utf-8')
    if namespace:
        payload = namespace.encode('utf-8') + b'\x00' + payload
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big', signed=True)


@asynccontextmanager
async def postgres_conversation_lock(dsn, customer, conversation, timeout=None):
    try:
        from psycopg import AsyncConnection
    except ImportError as exc:
        raise RuntimeError('Distributed locks require psycopg') from exc
    started = monotonic()
    from app.core.postgres_state import connection_options
    lock_key = advisory_key(customer, conversation)
    # Async connect avoids blocking the ASGI event loop while PostgreSQL
    # negotiates TLS or the database is unavailable.
    conn, locked = None, False
    try:
        # Bound connect AND acquisition; the caller's tool execution is outside
        # this deadline. Closing a failed/cancelled session releases its lock.
        async with asyncio.timeout(timeout):
            conn = await AsyncConnection.connect(dsn, connect_timeout=5, autocommit=True,
                options=connection_options(dsn,advisory=True))
            while True:
                cursor = await conn.execute('SELECT pg_try_advisory_lock(%s)', (lock_key,))
                locked = bool((await cursor.fetchone())[0])
                if locked:
                    break
                if timeout is not None and monotonic() - started >= timeout:
                    raise TimeoutError('session wait deadline exceeded')
                await asyncio.sleep(0.025)
        yield
    finally:
        if conn is not None:
            if locked:
                # Connection closing also releases session-scoped advisory locks.
                # An explicit unlock makes the happy path observable in SQL.
                try:
                    await asyncio.wait_for(asyncio.shield(conn.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))), 1)
                except Exception:
                    pass
            await conn.close()
