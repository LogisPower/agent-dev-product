"""Durable dispatch of existing canonical chat/build runs, without a second state store.

The PostgreSQL session advisory lock serializes dispatchers across processes.
Queued requests resume; a lost active request is reconciled, never auto-replayed.
Only nonsecret principal IDs and bounded invocation inputs are persisted.
"""
import json,threading,time,uuid
from psycopg.types.json import Jsonb
from contextlib import contextmanager

class Dispatcher:
    def __init__(self,db,resolve):
        self.db,self.resolve=db,resolve
        self.handlers={};self.stop=threading.Event();self.thread=None
        self.status='stopped';self.error_type=None

    def register(self,kind,handler):
        if kind in self.handlers:raise ValueError('Duplicate durable handler')
        self.handlers[kind]=handler

    def enqueue(self,project,run,kind,args,permissions,priority=10):
        principal=permissions.get('_dispatch_identity')
        if not principal:raise PermissionError('Durable dispatch requires a resolvable authenticated principal')
        if kind not in self.handlers:raise ValueError('Unknown durable handler')
        if len(json.dumps(args).encode())>180000:raise ValueError('Durable invocation exceeds bound')
        packet={'kind':kind,'args':args,'principal':principal,'priority':priority,'phase':'queued','attempts':0,'accepted':time.time()}
        with self.db(False) as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('logis-dispatch-admission'))")
            row=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s FOR UPDATE',(run,project)).fetchone()
            if not row or row['status']!='running':raise ValueError('Run no longer available for dispatch')
            if row['payload'].get('_dispatch'):return False
            if c.execute("SELECT count(*) AS n FROM logis_candidate.runs WHERE status='running' AND payload->'_dispatch'->>'phase' IN ('queued','active')").fetchone()['n']>=128:raise ValueError('Durable inference queue is full')
            c.execute('UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s',(Jsonb({'_dispatch':packet,'harness_phase':'queued'}),run))
        return True

    @contextmanager
    def ownership(self):
        with self.db(False) as c:
            if not c.execute("SELECT pg_try_advisory_lock(hashtext('logis-durable-inference')) AS owned").fetchone()['owned']:
                raise RuntimeError('Another durable dispatcher owns the inference queue')
            c.commit()
            try:yield
            finally:
                c.execute("SELECT pg_advisory_unlock(hashtext('logis-durable-inference'))")

    def recover(self):
        # Only call while holding ownership. The previous dispatcher session is gone.
        with self.db(False) as c:
            return c.execute("UPDATE logis_candidate.runs SET status='interrupted',payload=payload || %s WHERE status='running' AND payload->'_dispatch'->>'phase'='active'",(Jsonb({'notice':'Dispatcher stopped during execution. Original inputs and checkpoints retained. Inspect tool/artifact receipts before an intentional retry.','harness_phase':'needs_review'}),)).rowcount

    def once(self):
        with self.db(False) as c:
            row=c.execute("SELECT id,project_id,payload FROM logis_candidate.runs WHERE status='running' AND payload->'_dispatch'->>'phase'='queued' AND COALESCE((payload->'_dispatch'->>'available')::double precision,0)<=%s ORDER BY (payload->'_dispatch'->>'priority')::integer,(payload->'_dispatch'->>'accepted')::double precision LIMIT 1 FOR UPDATE SKIP LOCKED",(time.time(),)).fetchone()
            if not row:return False
            packet=row['payload']['_dispatch']
            if row['payload'].get('cancel_requested'):
                c.execute("UPDATE logis_candidate.runs SET status='canceled' WHERE id=%s",(row['id'],));return True
            packet={**packet,'phase':'active','attempts':packet['attempts']+1,'attempt_id':uuid.uuid4().hex}
            c.execute('UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s',(Jsonb({'_dispatch':packet,'harness_phase':'running'}),row['id']))
        try:
            permissions=self.resolve(packet['principal'])
            if not permissions.get('write') or row['project_id'] not in permissions.get('projects',[]):raise PermissionError('Queued principal revoked or project no longer authorized')
            with self.db() as c:
                project=c.execute('SELECT archived FROM logis_candidate.projects WHERE id=%s',(row['project_id'],)).fetchone()
            if not project or project['archived']:raise PermissionError('Project archived or removed')
            result=self.handlers[packet['kind']](row['project_id'],row['id'],packet['args'],permissions)
            # Retry only verified busy-before-dispatch outcomes, at most three attempts.
            if result and result.get('payload',{}).get('error_type')=='InferenceBusyError' and packet['attempts']<3:
                with self.db(False) as c:
                    current=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
                    p=current['payload']
                    if current['status']=='failed' and not any(p.get(k) for k in ('settled_effect','tool_receipts','cancel_requested','assistant_message_id')):
                        packet.update(phase='queued',available=time.time()+2**packet['attempts'])
                        c.execute("UPDATE logis_candidate.runs SET status='running',payload=payload || %s WHERE id=%s",(Jsonb({'_dispatch':packet,'harness_phase':'queued','notice':'Provider busy before work; bounded retry queued.'}),row['id']))
        except Exception as error:
            with self.db(False) as c:
                c.execute("UPDATE logis_candidate.runs SET status=CASE WHEN payload->>'cancel_requested'='true' THEN 'canceled' ELSE 'failed' END,payload=payload || %s WHERE id=%s AND status='running'",(Jsonb({'error_type':type(error).__name__,'notice':'Durable dispatcher failed; no automatic effect replay.'}),row['id']))
        return True

    def run(self):
        try:
            with self.ownership():
                self.recover();self.status='running'
                while not self.stop.is_set():
                    if not self.once():self.stop.wait(.25)
        except Exception as error:self.status='attention';self.error_type=type(error).__name__
        finally:
            if self.status!='attention':self.status='stopped'

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop.clear();self.thread=threading.Thread(target=self.run,daemon=True,name='logis-canonical-dispatch');self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
