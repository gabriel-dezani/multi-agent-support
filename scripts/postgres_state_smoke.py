"""Optional REAL PostgreSQL contract test (no model tokens, requires local DB).

DATABASE_URL must be set as TEST_POSTGRES_DSN to isolate test data.
The CI service spins up a disposable empty Postgres instance for this check.
"""
import asyncio
import os
import multiprocessing
import faulthandler
import logging
import signal
import sys
from contextlib import contextmanager
from time import perf_counter
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.core.postgres_state import (PostgresConversationMemoryStore, PostgresHandoffRepository,
                                     PostgresTelemetryRepository)
from app.core.distributed_lock import postgres_conversation_lock


@contextmanager
def stage(name):
    started = perf_counter()
    logging.info('stage=%s status=started', name)
    try:
        yield
    except BaseException:
        logging.info('stage=%s status=failed duration_s=%.3f', name, perf_counter() - started)
        raise
    else:
        logging.info('stage=%s status=completed duration_s=%.3f', name, perf_counter() - started)


def stop_on_signal(signum, frame):
    logging.error('smoke interrupted signal=%s; last started stage identifies the pending operation', signum)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    # Normal interpreter exit lets coverage save the parent process data.
    raise SystemExit(128 + signum)


def configure_diagnostics():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(process)d %(levelname)s %(message)s')
    faulthandler.enable()
    faulthandler.dump_traceback_later(60, repeat=True)
    signal.signal(signal.SIGTERM, stop_on_signal)


def hold_process_lock(dsn, owner, session, ready, release):
    from app.core.postgres_state import _connect
    from app.core.distributed_lock import advisory_key
    # Session locks need no open transaction while waiting for the parent.
    with _connect(dsn) as conn:
        conn.autocommit = True
        conn.execute('SELECT pg_advisory_lock(%s)',(advisory_key(owner,session),))
        ready.set()
        if not release.wait(10):
            raise TimeoutError('Test lock release signal missing')


def finish_process(process):
    """Bound cleanup even when terminate/coverage finalization gets stuck."""
    process.join(5)
    if process.is_alive():
        logging.warning('child pid=%s did not exit; terminating', process.pid)
        process.terminate()
        process.join(5)
    if process.is_alive():
        logging.error('child pid=%s ignored termination; killing', process.pid)
        process.kill()
        process.join(5)
    if process.is_alive():
        raise RuntimeError('Child could not be reaped')
    logging.info('child pid=%s exitcode=%s reaped', process.pid, process.exitcode)
    process.close()


async def process_checks(dsn, owner, session):
    context = multiprocessing.get_context('spawn')
    for terminate in (False,True):
        ready, release = context.Event(), context.Event()
        process = context.Process(target=hold_process_lock,args=(dsn,owner,session,ready,release))
        logging.info('multiprocess terminate=%s status=starting', terminate)
        with stage(f'child_start_terminate_{terminate}'):
            process.start()
        try:
            with stage(f'child_ready_terminate_{terminate}'):
                assert await asyncio.to_thread(ready.wait,5), 'Child did not acquire lock'
            logging.info('multiprocess terminate=%s pid=%s status=lock_acquired', terminate, process.pid)
            try:
                async with postgres_conversation_lock(dsn,owner,session,timeout=.1):
                    raise AssertionError('Lock bypassed a distinct process')
            except TimeoutError:
                pass
            with stage(f'child_exit_terminate_{terminate}'):
                if terminate:
                    process.terminate()
                else:
                    release.set()
                await asyncio.to_thread(process.join,5)
                assert not process.is_alive()
                if not terminate:
                    assert process.exitcode == 0
            with stage(f'lock_recovery_terminate_{terminate}'):
                async with postgres_conversation_lock(dsn,owner,session,timeout=3):
                    pass
        finally:
            # Never touch an Event after terminating its waiter: terminate
            # can leave the Event's internal condition mutex locked. A set()
            # here can hang the parent forever, outside all join deadlines.
            with stage(f'child_cleanup_terminate_{terminate}'):
                if process.is_alive():
                    process.terminate()
                await asyncio.to_thread(finish_process, process)


def main():
    dsn = os.environ.get('TEST_POSTGRES_DSN')
    if not dsn:
        raise RuntimeError('TEST_POSTGRES_DSN is required: use a disposable database')
    if urlsplit(dsn).hostname not in {'127.0.0.1','localhost','::1','postgres'}:
        raise ValueError('Only a disposable local/CI PostgreSQL service is allowed')
    import psycopg
    with stage('repository_initialization'):
        memory = PostgresConversationMemoryStore(dsn)
        handoffs = PostgresHandoffRepository(dsn)
        telemetry = PostgresTelemetryRepository(dsn)
    owner, session = 'pg-smoke-owner-'+str(uuid4()),str(uuid4())
    with stage('memory_atomicity_isolation_concurrency'):
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
    with stage('handoff_atomicity_concurrency_rollback'):
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
    with stage('telemetry'):
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
    with stage('async_advisory_locks_and_nested_memory_write'):
        asyncio.run(check_locks())
    with stage('multiprocess_lock_release_and_termination'):
        asyncio.run(process_checks(dsn, owner, session))
    with stage('connection_failure_recovery'):
        # A failed connection does not poison later repository calls (no cached
        # aborted connection). No retries of a possibly committed mutation.
        try:
            with psycopg.connect(dsn,host='127.0.0.1',port=1,connect_timeout=1):
                raise AssertionError('Unexpected PostgreSQL service on test failure port')
        except psycopg.OperationalError:
            pass
        assert memory.get_history(session,owner)
    with stage('long_turn_setup'):
        long_session = 'long-'+str(uuid4())
        memory.append_turn(long_session,owner,'Minhas vendas de ontem','ok','initial')
    with stage('1000_independent_committed_turns'):
        writes_started = perf_counter()
        for index in range(1000):
            memory.append_turn(long_session,owner,'E hoje?','ok',str(index))
            if (index + 1) % 100 == 0:
                elapsed = perf_counter() - writes_started
                logging.info('long_turn writes=%s duration_s=%.3f turns_per_s=%.2f',
                             index + 1, elapsed, (index + 1) / elapsed)
            if index+1 in {250,500,1000}:
                from app.orchestration.context import contextual_user_anchor
                with stage(f'restart_migration_{index + 1}'):
                    restarted = PostgresConversationMemoryStore(dsn)
                with stage(f'recovery_isolation_{index + 1}'):
                    history = restarted.get_history(long_session,owner,current_message='E isso?')
                    assert contextual_user_anchor('E isso?',history) == 'Minhas vendas de ontem'
                    assert memory.get_history(long_session,owner+'-other') == []
    with stage('cleanup'):
        assert memory.clear(long_session,owner) == 2002
        assert memory.clear(session,owner) == 3
    print('PostgreSQL memory/handoff/telemetry/advisory locks: OK')


if __name__=='__main__':
    configure_diagnostics()
    try:
        with stage('postgres_contract_total'):
            main()
    finally:
        faulthandler.cancel_dump_traceback_later()
