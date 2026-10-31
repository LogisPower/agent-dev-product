"""Bounded nonpreemptive scheduling. Durable run truth stays in PostgreSQL."""
import queue,threading,itertools,time
class WorkQueue:
    def __init__(self,limit=8):
        self.pending=queue.PriorityQueue(limit);self.counter=itertools.count();self.lock=threading.Lock();self.started=False;self.inflight=set()
    def submit(self,run,job,foreground=False):
        with self.lock:
            if run in self.inflight:return False
            if not self.started:
                threading.Thread(target=self._work,name='logis-harness-queue',daemon=True).start();self.started=True
            self.pending.put_nowait((0 if foreground else 10,next(self.counter),run,job,time.monotonic()))
            self.inflight.add(run)
            return True
    def _work(self):
        while True:
            _,_,run,job,created=self.pending.get()
            try:job(time.monotonic()-created)
            except Exception:pass # caller owns terminal/error persistence, never replay here
            finally:
                with self.lock:self.inflight.discard(run)
                self.pending.task_done()
def scheduler(app):
    # Registration is synchronous before requests start.
    if not hasattr(app.state,'harness_queue'):app.state.harness_queue=WorkQueue()
    return app.state.harness_queue
