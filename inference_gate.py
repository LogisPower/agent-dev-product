"""A shared, bounded inference gate for cooperating local Logis processes.

Main chat and extraction must use the SAME absolute lock path and hold this
context for the entire request/stream. Never delete the lock file: its inode
(or Windows file object) is the coordination point, not its contents.
"""
from contextlib import contextmanager
import errno
import math
import os
from pathlib import Path
import time

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class InferenceBusyError(TimeoutError):
    """Another cooperating process retained the inference slot past our limit."""


def _try_lock(handle):
    try:
        if os.name == 'nt':
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as error:
        # Do not conceal missing permissions, invalid handles or I/O failures.
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or (
                os.name == 'nt' and getattr(error, 'winerror', None) in (33, 36)):
            return False
        raise


def _unlock(handle):
    if os.name == 'nt':
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def inference_slot(lock_path, timeout=10.0, poll_interval=0.05):
    """Acquire a shared OS file lock, or raise InferenceBusyError by timeout.

    timeout=0 performs one non-blocking attempt. The containing directory must
    already exist. File handles are non-inheritable. The OS releases the lock
    on process termination, including crashes; no stale-file cleanup is needed.
    Only acquisition is time-bounded here. Callers must separately bound their
    model request/stream and must not use another inference path on busy errors.
    """
    timeout = float(timeout)
    poll_interval = float(poll_interval)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError('Inference lock timeout must be finite and non-negative')
    if not math.isfinite(poll_interval) or poll_interval <= 0:
        raise ValueError('Inference lock poll interval must be finite and positive')
    path = Path(lock_path)
    if not path.is_absolute():
        raise ValueError('Use one shared absolute inference lock path')
    deadline = time.monotonic() + timeout
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.set_inheritable(descriptor, False)
        handle = os.fdopen(descriptor, 'r+b', buffering=0)
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        # Lock a real byte on Windows. Concurrent initializers write the same
        # byte at offset zero; they never truncate, rename or delete this file.
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'\0')
        acquired = False
        try:
            while not acquired:
                acquired = _try_lock(handle)
                if acquired:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise InferenceBusyError(
                        'Local inference is busy with another Logis request. '
                        'No model request was started; retry after it finishes.')
                time.sleep(min(poll_interval, remaining))
            yield
        finally:
            if acquired:
                _unlock(handle)
