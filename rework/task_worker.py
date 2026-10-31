"""Bounded execution with OS dispatcher ownership and cooperative provider aborts."""
import contextlib
import threading
import time
import uuid
from pathlib import Path
from durable_tasks import Conflict


class Retryable(Exception):
    """Only for a known failure before any external effect has started."""


class Canceled(Exception):
    pass


class Attempt:
    def __init__(self, ledger, task):
        self.ledger, self.task = ledger, task
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.effect_started = False
        self.error = None

    def check(self):
        if self.error:
            raise self.error
        if self.cancelled.is_set():
            raise Canceled('Cancellation acknowledged')

    def checkpoint(self, value):
        self.check()
        if self.ledger.heartbeat(self.task['id'], self.task['token'], value):
            self.cancelled.set()
        self.check()

    def begin_effect(self, value):
        self.checkpoint({'phase': 'effect_started', **value})
        self.effect_started = True

    def monitor(self):
        while not self.finished.wait(0.2):
            try:
                if self.ledger.heartbeat(self.task['id'], self.task['token']):
                    self.cancelled.set()
            except Exception as error:
                self.error = error
                self.cancelled.set()
                return


class Worker:
    def __init__(self, ledger, handlers, files, authorize):
        self.ledger, self.handlers, self.files, self.authorize = ledger, handlers, files, authorize
        self.owner = uuid.uuid4().hex
        self.stop = threading.Event()
        self.thread = None
        self.status = 'stopped'
        self.error_type = None

    def once(self):
        task = self.ledger.claim(self.owner)
        if not task:
            return False
        attempt = Attempt(self.ledger, task)
        monitor = threading.Thread(target=attempt.monitor, daemon=True)
        monitor.start()
        try:
            if not self.authorize(task):
                raise PermissionError('Task scope/grant revoked; no execution')
            if task['kind'] not in self.handlers:
                raise ValueError('Task handler is unavailable')
            files = self.files(task['project'])
            for dep in task['dependencies']:
                files.verify(dep['path'], dep['sha256'])
            attempt.checkpoint({'phase': 'dispatched', 'dependencies_verified': len(task['dependencies'])})
            payload={k:v for k,v in task['payload'].items() if k!='_principal'}
            if task['kind']=='file_read':
                versions={dep['sha256'] for dep in task['dependencies'] if dep['path']==payload.get('path')}
                if len(versions)>1:raise ValueError('Conflicting dependency versions')
                if versions:
                    expected=next(iter(versions))
                    if payload.get('expected_sha256') not in (None,expected):raise ValueError('Read version conflicts with dependency')
                    payload['expected_sha256']=expected
            result, artifacts = self.handlers[task['kind']](attempt, files, payload)
            attempt.check()
            self.ledger.finish(task['id'], task['token'], 'completed', result, artifacts)
        except Retryable as error:
            if attempt.effect_started:
                self.ledger.finish(task['id'], task['token'], 'needs_review', {'reason': type(error).__name__, 'effect_started': True})
            else:
                self.ledger.retry(task['id'], task['token'], str(error)[:200])
        except Exception as error:
            try:
                status = 'needs_review' if attempt.effect_started else 'canceled' if isinstance(error, Canceled) else 'failed'
                self.ledger.finish(task['id'], task['token'], status, {'reason': type(error).__name__, 'effect_started': attempt.effect_started, 'notice': 'Inspect checkpoint and receipt; effects are not undone.'})
            except Conflict:
                pass  # Fenced result rejected; recovery owns the uncertain attempt.
        finally:
            attempt.finished.set()
            monitor.join(timeout=2)
        return True

    def run(self):
        from inference_gate import inference_slot
        try:
            with inference_slot(self.ledger.path.with_suffix('.dispatcher.lock').absolute(), timeout=0):
                self.ledger.recover(exclusive_restart=True)
                self.status = 'running'
                while not self.stop.is_set():
                    self.ledger.recover()
                    if not self.once():
                        self.stop.wait(0.25)
        except Exception as error:
            self.status, self.error_type = 'attention', type(error).__name__
        finally:
            if self.status != 'attention':
                self.status = 'stopped'

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(target=self.run, daemon=True, name='logis-durable-worker')
        self.thread.start()

    def close(self):
        # Finish bounded active work, stop claiming new tasks. No forced replay.
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)


def file_read(attempt, files, payload):
    attempt.check()
    return files.read(**payload), []


def file_write(attempt, files, payload):
    attempt.begin_effect({'path': payload['path'], 'receipt_id': attempt.task['id']})
    result = files.write(**payload, request_id=attempt.task['id'])
    return {'receipt': result['receipt'], 'effect_started': True}, [result['artifact']]


FILE_HANDLERS = {'file_read': file_read, 'file_write': file_write}
