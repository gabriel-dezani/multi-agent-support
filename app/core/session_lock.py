"""Serialize a session within one service process, across event loops/threads.

Weak references prevent retaining locks for arbitrary expired sessions. Waiting
does not occupy the executor needed by LangGraph nodes. Cancellation releases
an acquired lock. Multi-process deployments require a distributed equivalent.
"""
import asyncio
from contextlib import asynccontextmanager
from threading import Lock
from weakref import WeakValueDictionary

_registry_guard = Lock()
_locks = WeakValueDictionary()


@asynccontextmanager
async def conversation_lock(key, timeout=None):
    with _registry_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = Lock()
            _locks[key] = lock
    started = asyncio.get_running_loop().time()
    while not lock.acquire(blocking=False):
        if timeout is not None and asyncio.get_running_loop().time() - started >= timeout:
            raise TimeoutError("session wait deadline exceeded")
        await asyncio.sleep(.002)
    try:
        yield
    finally:
        lock.release()
