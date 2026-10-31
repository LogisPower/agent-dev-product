"""Durable, single-dispatcher task ledger. No credentials or executable closures stored.

External effects are at-least-once/uncertain, never advertised as exactly once.
Lost attempts require reconciliation; only pre-effect Retryable failures retry.
"""
import contextlib
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

TERMINAL = {'completed', 'failed', 'canceled'}
ACTIVE = {'running', 'cancel_requested'}


def encoded(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    if len(raw.encode()) > 131072:
        raise ValueError('Task data exceeds 128 KiB')
    return raw


class Conflict(ValueError):
    pass


class Ledger:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY, project TEXT NOT NULL, request_key TEXT NOT NULL,
                  fingerprint TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  outputs TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL,
                  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
                  token TEXT, owner TEXT, lease_until REAL, available REAL NOT NULL,
                  checkpoint TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT '{}',
                  created REAL NOT NULL, updated REAL NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                  UNIQUE(project,request_key));
                CREATE TABLE IF NOT EXISTS dependencies(
                  job TEXT NOT NULL REFERENCES jobs(id), creator TEXT NOT NULL REFERENCES jobs(id),
                  path TEXT NOT NULL, PRIMARY KEY(job,creator,path));
                CREATE TABLE IF NOT EXISTS artifacts(
                  job TEXT NOT NULL REFERENCES jobs(id), path TEXT NOT NULL, sha256 TEXT NOT NULL,
                  evidence TEXT NOT NULL, PRIMARY KEY(job,path));
                CREATE TABLE IF NOT EXISTS ownership(
                  project TEXT NOT NULL, path TEXT NOT NULL, job TEXT NOT NULL REFERENCES jobs(id),
                  PRIMARY KEY(project,path));
                CREATE TABLE IF NOT EXISTS task_events(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL REFERENCES jobs(id),
                  status TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS queue_ready ON jobs(status,available,priority,created);
                CREATE TABLE IF NOT EXISTS task_contexts(
                  job TEXT NOT NULL REFERENCES jobs(id), sha256 TEXT NOT NULL,
                  original TEXT NOT NULL, PRIMARY KEY(job,sha256));
                CREATE TABLE IF NOT EXISTS compaction_attempts(
                  job TEXT PRIMARY KEY REFERENCES jobs(id), attempts INTEGER NOT NULL);
            ''')

    @contextlib.contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA synchronous=FULL')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            yield c

    def event(self, c, job, status, detail):
        c.execute('INSERT INTO task_events(job,status,detail,created) VALUES(?,?,?,?)',
                  (job, status, encoded(detail), self.clock()))

    @staticmethod
    def unpack(row):
        if row is None:
            raise KeyError('Task not found in project')
        value = dict(row)
        for key in ('payload', 'outputs', 'checkpoint', 'result'):
            value[key] = json.loads(value[key])
        return value

    def get(self, project, job):
        with self.connection() as c:
            value = self.unpack(c.execute('SELECT * FROM jobs WHERE id=? AND project=?', (job, project)).fetchone())
            value['artifacts'] = [dict(r) for r in c.execute('SELECT path,sha256,evidence FROM artifacts WHERE job=?', (job,))]
            value['dependencies'] = [dict(r) for r in c.execute('SELECT creator,path FROM dependencies WHERE job=?', (job,))]
            return value

    def has_active(self, project=None):
        with self.connection() as c:
            return c.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancel_requested') AND (? IS NULL OR project=?) LIMIT 1",(project,project)).fetchone() is not None

    def get_checkpoint(self,job):
        with self.connection() as c:
            row=c.execute('SELECT checkpoint FROM jobs WHERE id=?',(job,)).fetchone()
            if not row:raise KeyError('Task not found')
            return json.loads(row['checkpoint'])

    def list(self, project, after=0, limit=50):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid task page')
        with self.connection() as c:
            # Event cursor, not offsets into a changing status list.
            events = [dict(r) for r in c.execute('SELECT e.* FROM task_events e JOIN jobs j ON e.job=j.id WHERE j.project=? AND e.sequence>? ORDER BY e.sequence LIMIT ?', (project, after, limit + 1))]
            more = len(events) > limit
            events = events[:limit]
            identifiers=list(dict.fromkeys(e['job'] for e in events))
            if identifiers:
                marks=','.join('?' for _ in identifiers)
                affected=c.execute("SELECT DISTINCT d.job FROM dependencies d JOIN jobs j ON j.id=d.job WHERE j.project=? AND j.status IN ('waiting','approval','queued') AND d.creator IN ("+marks+") LIMIT 128",(project,*identifiers)).fetchall()
                identifiers=list(dict.fromkeys([*identifiers,*(r['job'] for r in affected)]))
            tasks = [self.unpack(c.execute('SELECT * FROM jobs WHERE id=?', (j,)).fetchone()) for j in identifiers]
            for task in tasks:
                task['dependencies']=[dict(r) for r in c.execute('SELECT d.creator AS task,d.path,j.status,a.sha256 FROM dependencies d JOIN jobs j ON j.id=d.creator LEFT JOIN artifacts a ON a.job=d.creator AND a.path=d.path WHERE d.job=?',(task['id'],))]
            return {'tasks': tasks, 'events': events, 'next_cursor': events[-1]['sequence'] if events else after, 'has_more': more}

    def submit(self, project, request_key, kind, payload, *, outputs=(), dependencies=(), priority=10, max_attempts=3, approval=False, _connection=None):
        from workspace_files import relative
        if not all(isinstance(x, str) and 1 <= len(x) <= 200 for x in (project, request_key, kind)):
            raise ValueError('Project, kind and idempotency key required')
        if type(priority) is not int or not 0 <= priority <= 20 or type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError('Invalid bounded queue policy')
        outputs = sorted(set(outputs))
        if len(outputs) > 16 or len(dependencies) > 16 or len({p.casefold() for p in outputs}) != len(outputs):
            raise ValueError('Invalid artifact declarations')
        for path in outputs:
            relative(path)
        contract = dict(kind=kind, payload=payload, outputs=outputs, dependencies=list(dependencies), priority=priority, max_attempts=max_attempts, approval=bool(approval))
        fingerprint = hashlib.sha256(encoded(contract).encode()).hexdigest()
        with (self.transaction() if _connection is None else contextlib.nullcontext(_connection)) as c:
            old = c.execute('SELECT * FROM jobs WHERE project=? AND request_key=?', (project, request_key)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise Conflict('Idempotency key already belongs to a different task')
                return {**self.unpack(old), 'replayed': True}
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','waiting','approval','running','cancel_requested')").fetchone()[0] >= 128:
                raise Conflict('Durable queue is full (128 pending/active tasks); nothing accepted')
            identifier, now = uuid.uuid4().hex, self.clock()
            status = 'approval' if approval else 'waiting' if dependencies else 'queued'
            c.execute('INSERT INTO jobs(id,project,request_key,fingerprint,kind,payload,outputs,status,priority,max_attempts,available,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (identifier, project, request_key, fingerprint, kind, encoded(payload), encoded(outputs), status, priority, max_attempts, now, now, now))
            for dep in dependencies:
                if set(dep) != {'task', 'path'}:
                    raise ValueError('Dependency requires creator task and declared artifact path')
                relative(dep['path'])
                creator = c.execute('SELECT outputs FROM jobs WHERE id=? AND project=?', (dep['task'], project)).fetchone()
                if not creator or dep['path'] not in json.loads(creator['outputs']):
                    raise ValueError('Dependency creator has not declared this project artifact')
                c.execute('INSERT INTO dependencies VALUES(?,?,?)', (identifier, dep['task'], dep['path']))
            self.event(c, identifier, status, {'accepted': True})
        if _connection is not None:
            return self.unpack(_connection.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone())
        return self.get(project, identifier)

    def submit_verified_write(self, project, request_key, payload, dependencies=(), *, _connection=None):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 180:
            raise ValueError('Bounded workflow idempotency key required')
        with (self.transaction() if _connection is None else contextlib.nullcontext(_connection)) as c:
            writer = self.submit(project, request_key + ':write', 'file_write', payload,
                                 outputs=[payload['path']], dependencies=dependencies, approval=True, _connection=c)
            read_payload = {'path': payload['path']}
            if '_principal' in payload:
                read_payload['_principal'] = payload['_principal']
            reader = self.submit(project, request_key + ':verify', 'file_read', read_payload,
                                 dependencies=[{'task': writer['id'], 'path': payload['path']}], _connection=c)
        return {'write': writer, 'verify': reader}

    def approve(self, project, job, version):
        with self.transaction() as c:
            changed = c.execute("UPDATE jobs SET status='waiting',version=version+1,updated=? WHERE id=? AND project=? AND status='approval' AND version=?", (self.clock(), job, project, version)).rowcount
            if not changed:
                raise Conflict('Approval changed; reload task')
            self.event(c, job, 'waiting', {'approved_version': version})
        return self.get(project, job)

    def claim(self, owner, lease_seconds=30):
        if not 1 <= lease_seconds <= 300:
            raise ValueError('Invalid lease')
        with self.transaction() as c:
            now = self.clock()
            if c.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancel_requested') LIMIT 1").fetchone():
                return None  # One slot even if multiple dispatcher instances race.
            for row in c.execute("SELECT * FROM jobs WHERE status IN ('queued','waiting') AND available<=? ORDER BY priority,created LIMIT 128", (now,)).fetchall():
                deps = c.execute('SELECT d.creator,d.path,j.status,a.sha256 FROM dependencies d JOIN jobs j ON j.id=d.creator LEFT JOIN artifacts a ON a.job=d.creator AND a.path=d.path WHERE d.job=?', (row['id'],)).fetchall()
                blocked = [{'task': d['creator'], 'status': d['status']} for d in deps if d['status'] in ('failed', 'canceled')]
                if blocked:
                    result = {'reason': 'Dependency cannot produce committed artifact', 'blocked_by': blocked, 'effect_started': False}
                    c.execute("UPDATE jobs SET status='canceled',result=?,updated=?,version=version+1 WHERE id=?", (encoded(result), now, row['id']))
                    self.event(c, row['id'], 'canceled', result)
                    continue
                if any(d['status'] == 'needs_review' for d in deps):
                    continue
                if any(d['status'] != 'completed' or not d['sha256'] for d in deps):
                    continue
                outputs = json.loads(row['outputs'])
                if any(c.execute('SELECT 1 FROM ownership WHERE project=? AND path=? AND job<>?', (row['project'], p.casefold(), row['id'])).fetchone() for p in outputs):
                    continue
                token = uuid.uuid4().hex
                for path in outputs:
                    c.execute('INSERT OR IGNORE INTO ownership VALUES(?,?,?)', (row['project'], path.casefold(), row['id']))
                c.execute("UPDATE jobs SET status='running',attempts=attempts+1,token=?,owner=?,lease_until=?,updated=?,version=version+1 WHERE id=?", (token, owner, now + lease_seconds, now, row['id']))
                self.event(c, row['id'], 'running', {'attempt': row['attempts'] + 1})
                result = self.unpack(c.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone())
                result['dependencies'] = [dict(d) for d in deps]
                return result
        return None

    def fenced(self, c, job, token):
        row = c.execute("SELECT * FROM jobs WHERE id=? AND token=? AND status IN ('running','cancel_requested') AND lease_until>?", (job, token, self.clock())).fetchone()
        if not row:
            raise Conflict('Attempt lost ownership; result not accepted')
        return row

    def heartbeat(self, job, token, checkpoint=None):
        with self.transaction() as c:
            row = self.fenced(c, job, token)
            c.execute('UPDATE jobs SET lease_until=?,checkpoint=?,updated=? WHERE id=?', (self.clock() + 30, encoded(checkpoint) if checkpoint is not None else row['checkpoint'], self.clock(), job))
            return row['status'] == 'cancel_requested'

    def preserve_context(self,job,token,original):
        if len(original.encode())>1048576:raise ValueError('Original context exceeds archival bound; no compaction attempted')
        checksum=hashlib.sha256(original.encode()).hexdigest()
        with self.transaction() as c:
            self.fenced(c,job,token)
            c.execute('INSERT OR IGNORE INTO task_contexts VALUES(?,?,?)',(job,checksum,original))
        return checksum

    def reserve_compaction(self,job,token):
        with self.transaction() as c:
            self.fenced(c,job,token)
            row=c.execute('SELECT attempts FROM compaction_attempts WHERE job=?',(job,)).fetchone()
            attempts=row['attempts'] if row else 0
            if attempts>=2:raise Conflict('Compaction limit reached; original context retained')
            c.execute('INSERT INTO compaction_attempts VALUES(?,?) ON CONFLICT(job) DO UPDATE SET attempts=excluded.attempts',(job,attempts+1))
            return attempts+1

    def reconcile(self,project,job,version,result,artifacts):
        """Explicit acceptance of independently verified existing effects, never re-execution."""
        with self.transaction() as c:
            row=c.execute("SELECT * FROM jobs WHERE id=? AND project=? AND version=? AND status='needs_review'",(job,project,version)).fetchone()
            if not row:raise Conflict('Recovery task changed; reload evidence')
            if set(json.loads(row['outputs']))!={a['path'] for a in artifacts}:raise ValueError('All outputs must be verified')
            for artifact in artifacts:
                c.execute('INSERT INTO artifacts VALUES(?,?,?,?) ON CONFLICT(job,path) DO UPDATE SET sha256=excluded.sha256,evidence=excluded.evidence',(job,artifact['path'],artifact['sha256'],encoded(artifact)))
            c.execute("UPDATE jobs SET status='completed',result=?,version=version+1,updated=? WHERE id=?",(encoded(result),self.clock(),job))
            c.execute('DELETE FROM ownership WHERE job=?',(job,))
            self.event(c,job,'completed',{'reconciled':True,'reexecuted':False})
        return self.get(project,job)

    def cancel(self, project, job):
        with self.transaction() as c:
            row = c.execute('SELECT * FROM jobs WHERE id=? AND project=?', (job, project)).fetchone()
            if not row:
                raise KeyError('Task not found in project')
            if row['status'] in TERMINAL or row['status'] == 'needs_review':
                return self.unpack(row)
            status = 'cancel_requested' if row['status'] in ACTIVE else 'canceled'
            c.execute('UPDATE jobs SET status=?,updated=?,version=version+1 WHERE id=?', (status, self.clock(), job))
            self.event(c, job, status, {'effects_undone': False})
        return self.get(project, job)

    def finish(self, job, token, status, result, artifacts=()):
        import re
        if status not in TERMINAL | {'needs_review'}:
            raise ValueError('Invalid terminal status')
        with self.transaction() as c:
            row = self.fenced(c, job, token)
            if row['status'] == 'cancel_requested':
                status = 'needs_review' if artifacts or result.get('effect_started') else 'canceled'
                if status == 'canceled':
                    result = {'notice': 'Late result withheld after cancellation', 'effect_started': False}
            if status == 'completed' and set(json.loads(row['outputs'])) != {a['path'] for a in artifacts}:
                raise ValueError('Completion requires all declared artifact evidence')
            for artifact in artifacts:
                if artifact['path'] not in json.loads(row['outputs']) or not re.fullmatch('[a-f0-9]{64}', artifact['sha256']):
                    raise ValueError('Invalid artifact evidence')
                c.execute('INSERT INTO artifacts VALUES(?,?,?,?)', (job, artifact['path'], artifact['sha256'], encoded(artifact)))
            c.execute('UPDATE jobs SET status=?,result=?,token=NULL,lease_until=NULL,updated=?,version=version+1 WHERE id=?', (status, encoded(result), self.clock(), job))
            if status != 'needs_review':
                c.execute('DELETE FROM ownership WHERE job=?', (job,))
            self.event(c, job, status, result)

    def retry(self, job, token, reason):
        """Caller must establish no effect started; uncertain failures use finish(needs_review)."""
        with self.transaction() as c:
            row = self.fenced(c, job, token)
            status = 'canceled' if row['status'] == 'cancel_requested' else 'queued' if row['attempts'] < row['max_attempts'] else 'failed'
            c.execute('UPDATE jobs SET status=?,token=NULL,lease_until=NULL,available=?,updated=?,version=version+1,result=? WHERE id=?', (status, self.clock() + min(60, 2 ** row['attempts']), self.clock(), encoded({'reason': reason, 'effect_started': False}), job))
            c.execute('DELETE FROM ownership WHERE job=?', (job,))
            self.event(c, job, status, {'reason': reason, 'retry_bounded': True})

    def recover(self, *, exclusive_restart=False):
        """exclusive_restart requires caller to hold the dispatcher OS lock."""
        with self.transaction() as c:
            query = "SELECT id FROM jobs WHERE status IN ('running','cancel_requested')"
            rows = c.execute(query if exclusive_restart else query + ' AND lease_until<=?', () if exclusive_restart else (self.clock(),)).fetchall()
            for row in rows:
                c.execute("UPDATE jobs SET status='needs_review',token=NULL,lease_until=NULL,updated=?,version=version+1 WHERE id=?", (self.clock(), row['id']))
                self.event(c, row['id'], 'needs_review', {'reason': 'Dispatcher stopped or lease expired; inspect checkpoint and filesystem receipt. No automatic replay.'})
            return len(rows)
