import asyncio
import sqlite3

import pytest
from app.core.telemetry import TelemetryRepository
from app.core.session_lock import conversation_lock


def test_legacy_telemetry_migration_preserves_existing_requests_and_spans(tmp_path):
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE request_stats(request_id TEXT PRIMARY KEY,user_ref TEXT,route TEXT,latency_ms REAL,escalated INTEGER,degraded INTEGER,agents_count INTEGER,input_tokens INTEGER,output_tokens INTEGER,estimated_cost_usd REAL,retrieval_hits INTEGER,retrieval_best_score REAL,created_at TEXT)")
        db.execute("CREATE TABLE request_spans(request_id TEXT,seq INTEGER,agent TEXT,duration_ms REAL,status TEXT,PRIMARY KEY(request_id,seq))")
        db.execute("INSERT INTO request_stats(request_id,user_ref,route,latency_ms,escalated,degraded,agents_count) VALUES('old-request','synthetic-hash','knowledge',10,0,0,1)")
        db.execute("INSERT INTO request_spans VALUES('old-request',0,'knowledge',9,'ok')")
    repo = TelemetryRepository(path)
    assert repo.request("old-request")["user_ref"] == "synthetic-hash"
    assert repo.trace("old-request")[0]["status"] == "ok"
    repo.record(request_id="new-request",user_ref="synthetic-hash",route="knowledge",latency_ms=3,
                escalated=False,degraded=False,spans=[],session_ref="session-hash")
    assert repo.stats()["requests"] == 2
    assert repo.stats()["tickets_pending"] is None
    assert TelemetryRepository(path).request("new-request")["session_ref"] == "session-hash"


def test_cancelled_session_waiter_does_not_leak_lock():
    async def exercise():
        async def waiter():
            async with conversation_lock(("synthetic-db", "alice", "session")):
                pytest.fail("waiter must not enter while holder owns the lock")
        async with conversation_lock(("synthetic-db", "alice", "session")):
            task = asyncio.create_task(waiter())
            await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        async def reacquire():
            async with conversation_lock(("synthetic-db", "alice", "session")):
                return True
        assert await asyncio.wait_for(reacquire(), .5)
    asyncio.run(exercise())
