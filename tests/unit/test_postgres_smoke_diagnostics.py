"""Offline regressions for the smoke runner, including unsafe Event cleanup."""
import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from scripts import postgres_state_smoke as smoke


def test_stage_logs_failure_and_duration_even_on_cancellation(caplog):
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit):
        with smoke.stage('blocked_operation'):
            raise SystemExit(143)
    assert 'stage=blocked_operation status=started' in caplog.text
    assert 'stage=blocked_operation status=failed duration_s=' in caplog.text


def test_process_contract_never_sets_event_after_terminating_waiter(monkeypatch):
    processes = []

    class Event:
        def __init__(self):
            self.signalled = False

        def wait(self, timeout):
            return self.signalled

        def set(self):
            # Model a condition mutex orphaned by terminate(). Touching this
            # Event would deadlock in the real runner rather than raise.
            assert not processes or not processes[-1].terminated
            self.signalled = True

    class Process:
        pid = 123
        exitcode = None
        terminated = False
        alive = False

        def __init__(self, target, args):
            self.ready, self.release = args[-2:]
            self.closed = False
            processes.append(self)

        def start(self):
            self.alive = True
            self.ready.set()

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False
            self.exitcode = -15

        def join(self, timeout):
            if self.release.signalled and not self.terminated:
                self.alive = False
                self.exitcode = 0

        def close(self):
            assert not self.alive
            self.closed = True

    @asynccontextmanager
    async def lock(*args, **kwargs):
        if processes[-1].alive:
            raise TimeoutError('held by child')
        yield

    monkeypatch.setattr(smoke.multiprocessing, 'get_context',
                        lambda method: SimpleNamespace(Event=Event, Process=Process))
    monkeypatch.setattr(smoke, 'postgres_conversation_lock', lock)
    asyncio.run(smoke.process_checks('unused', 'owner', 'session'))
    assert len(processes) == 2
    assert processes[0].release.signalled
    assert processes[1].terminated and not processes[1].release.signalled
    assert all(process.closed for process in processes)


def test_cleanup_kills_and_reaps_child_that_ignores_terminate():
    calls = []

    class Process:
        pid = 456
        exitcode = None
        alive = True

        def join(self, timeout):
            calls.append(('join', timeout))

        def is_alive(self):
            return self.alive

        def terminate(self):
            calls.append('terminate')

        def kill(self):
            calls.append('kill')
            self.alive = False
            self.exitcode = -9

        def close(self):
            calls.append('close')

    smoke.finish_process(Process())
    assert calls == [('join', 5), 'terminate', ('join', 5), 'kill', ('join', 5), 'close']
