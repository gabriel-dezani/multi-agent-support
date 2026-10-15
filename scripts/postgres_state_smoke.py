"""Optional REAL PostgreSQL contract test (no model tokens, requires local DB).

DATABASE_URL must be set as TEST_POSTGRES_DSN to isolate test data.
The CI service spins up a disposable empty Postgres instance for this check.
"""
import asyncio
import os
import multiprocessing
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.core.postgres_state import (PostgresConversationMemoryStore, PostgresHandoffRepository,
                                     PostgresTelemetryRepository)
from app.core.distributed_lock import postgres_conversation_lock


def hold_process_lock(dsn, owner, session, ready, release):
    from app.core.postgres_state import _connect
    from app.core.distributed_lock import advisory_key
    with _connect(dsn) as conn:
        conn.execute('SELECT pg_advisory_lock(%s)',(advisory_key(owner,session),))
        ready.set()
        if not release.wait(10):
            raise TimeoutError('Test lock release signal missing')


def main():
    dsn = os.environ.get('TEST_POSTGRES_DSN')
    if not dsn:
        raise RuntimeError('TEST_POSTGRES_DSN is required: use a disposable database')
    if urlsplit(dsn).hostname not in {'127.0.0.1','localhost','::1','postgres'}:
        raise ValueError('Only a disposable local/CI PostgreSQL service is allowed')
    import psycopg
    memory = PostgresConversationMemoryStore(dsn)
    handoffs = PostgresHandoffRepository(dsn)
    telemetry = PostgresTelemetryRepository(dsn)
    owner, session = 'pg-smoke-owner-'+str(uuid4()),str(uuid4())
    memory.append_turn(session,owner,'Minha venda de ontem','Vendas','req-1')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: memory.append_turn(session,owner,'Minha venda de ontem','Vendas','req-1'),range(20)))
    try:
        memory.append_turn(session,owner,'conflicting payload','Vendas','req-1')
        raise AssertionError('Conflicting request was accepted')
    except ValueError:
        pass
    # Second-row failure must roll back the first row and release the xact lock.
    try:
        memory.append_turn(session,owner,'must rollback',None,'failed-turn')
        raise AssertionError('NULL assistant content was accepted')
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
    assert [x['role'] for x in memory.get_history(session,owner)] == ['user','assistant']
    assert memory.get_history(session, owner + '-other') == []
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: handoffs.create(request_id=str(uuid4()),
            conversation_id=session,user_id=owner,reason='human',summary='summary'),range(20)))
    assert len({r['handoff_id'] for r in records}) == 1
    ticket_id = records[0]['handoff_id']
    assert handoffs.pending(session,owner)['handoff_id'] == ticket_id
    try:
        handoffs.resolve(ticket_id,resolution=None,resolved_by='operator',append_memory=True)
        raise AssertionError('Human-memory write should fail and roll back ticket transition')
    except psycopg.errors.NotNullViolation:
        pass
    assert handoffs.pending(session,owner)['handoff_id'] == ticket_id
    assert handoffs.resolve(ticket_id,resolution='human answer',resolved_by='operator',
                            append_memory=True)['_transitioned'] is True
    assert handoffs.resolve(ticket_id,resolution='different answer',resolved_by='operator',
                            append_memory=True)['_transitioned'] is False
    assert [x['content'] for x in memory.get_history(session,owner)].count('human answer') == 1
    identifier = str(uuid4())
    telemetry.record(request_id=identifier,user_ref='ref',route='knowledge',latency_ms=123,
                     escalated=False,degraded=False,spans=[{'agent':'knowledge','duration_ms':8,'status':'ok'}],
                     agents=['knowledge'],usage_complete=True)
    assert telemetry.request(identifier)['route'] == 'knowledge'
    assert telemetry.trace(identifier)[0]['agent'] == 'knowledge'
    assert telemetry.rate(identifier,'ref',5)
    assert telemetry.stats()['requests'] >= 1
    assert telemetry.recent_stats()['requests'] >= 1
    async def check_locks():
        order=[]
        active = 0
        max_active = 0
        async def one():
            nonlocal active, max_active
            async with postgres_conversation_lock(dsn,owner,session,timeout=3):
                active += 1
                max_active = max(active, max_active)
                order.append('acquired')
                await asyncio.sleep(.07)
                active -= 1
        await asyncio.gather(one(),one())
        assert len(order)==2 and max_active == 1
        # A different key must not serialize behind this one.
        async with postgres_conversation_lock(dsn,owner,session,timeout=3):
            # The request-level session lock and the memory transaction use
            # distinct namespaces/connections; persisting a turn must not wait
            # for its own HTTP request to release the outer lock.
            await asyncio.wait_for(asyncio.to_thread(memory.append_turn,
                session,owner,'Minha venda de ontem','Vendas','req-1'),timeout=3)
            async with postgres_conversation_lock(dsn,owner,session+'other',timeout=3):
                pass
            try:
                async with postgres_conversation_lock(dsn,owner,session,timeout=.05):
                    raise AssertionError('Same session acquired twice')
            except TimeoutError:
                pass
    asyncio.run(check_locks())
    async def process_checks():
        context = multiprocessing.get_context('spawn')
        for terminate in (False,True):
            ready, release = context.Event(), context.Event()
            process = context.Process(target=hold_process_lock,args=(dsn,owner,session,ready,release))
            process.start()
            try:
                assert await asyncio.to_thread(ready.wait,5), 'Child did not acquire lock'
                try:
                    async with postgres_conversation_lock(dsn,owner,session,timeout=.1):
                        raise AssertionError('Lock bypassed a distinct process')
                except TimeoutError:
                    pass
                if terminate:
                    process.terminate()
                else:
                    release.set()
                await asyncio.to_thread(process.join,5)
                assert not process.is_alive()
                if not terminate:
                    assert process.exitcode == 0
                async with postgres_conversation_lock(dsn,owner,session,timeout=3):
                    pass
            finally:
                release.set()
                if process.is_alive():
                    process.terminate()
                await asyncio.to_thread(process.join,5)
    asyncio.run(process_checks())
    # A failed connection does not poison later repository calls (no cached
    # aborted connection). No retries of a possibly committed mutation.
    try:
        with psycopg.connect(dsn,host='127.0.0.1',port=1,connect_timeout=1):
            raise AssertionError('Unexpected PostgreSQL service on test failure port')
    except psycopg.OperationalError:
        pass
    assert memory.get_history(session,owner)
    long_session = 'long-'+str(uuid4())
    memory.append_turn(long_session,owner,'Minhas vendas de ontem','ok','initial')
    for index in range(1000):
        memory.append_turn(long_session,owner,'E hoje?','ok',str(index))
        if index+1 in {250,500,1000}:
            from app.orchestration.context import contextual_user_anchor
            history = PostgresConversationMemoryStore(dsn).get_history(long_session,owner,current_message='E isso?')
            assert contextual_user_anchor('E isso?',history) == 'Minhas vendas de ontem'
            assert memory.get_history(long_session,owner+'-other') == []
    assert memory.clear(long_session,owner) == 2002
    assert memory.clear(session,owner) == 3
    print('PostgreSQL memory/handoff/telemetry/advisory locks: OK')


if __name__=='__main__':
    main()
