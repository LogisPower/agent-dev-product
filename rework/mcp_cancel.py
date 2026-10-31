"""Process-local fast cancellation for bounded MCP calls; DB remains authoritative.

Register before the existing durable dispatch check. Signal only after committed
user cancellation. No storage query occurs inside the MCP protocol deadline.
Cross-process/external DB changes are checked by existing final commit guards;
this signal does not promise immediate cross-process preemption.
"""
import threading
from contextlib import contextmanager
_lock=threading.Lock()
_active={}
@contextmanager
def watch(run):
    with _lock:
        if run in _active or len(_active)>=128:raise RuntimeError('MCP cancellation registration unavailable')
        event=threading.Event();_active[run]=event
    try:yield event
    finally:
        with _lock:
            if _active.get(run) is event:del _active[run]
def signal(run):
    with _lock:
        event=_active.get(run)
        if event is not None:event.set()
def current(run):
    with _lock:
        event=_active.get(run)
        if event is None:raise RuntimeError('MCP cancellation signal not registered')
        return event
