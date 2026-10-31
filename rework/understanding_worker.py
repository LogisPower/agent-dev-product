"""Restartable extraction of candidate messages; never executes suggested tasks."""
import uuid,threading
from outbox_worker import Worker as ConnectionProvider
from conversation_understanding import suggest,local_model
from psycopg.types.json import Jsonb

class UnderstandingWorker(ConnectionProvider):
    def __init__(self,dsn,request_model=None,slot=None):
        super().__init__(dsn,max_attempts=3)
        self.request_model=request_model or local_model
        self.slot=slot or threading.BoundedSemaphore(1)
    def claim(self,identifier=None):
        token=uuid.uuid4().hex
        with self.connect() as db:
            db.execute("UPDATE logis_candidate.understanding_jobs SET version=version+1,status='failed',last_error='LeaseExpired',lease_until=NULL,lease_token=NULL WHERE status='running' AND attempts>=3 AND lease_until<now()")
            row=db.execute("SELECT * FROM logis_candidate.understanding_jobs WHERE attempts<3 AND status IN ('pending','running') AND available_at<=now() AND (lease_until IS NULL OR lease_until<now()) AND (%s::text IS NULL OR id=%s) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1",(identifier,identifier)).fetchone()
            if not row:return None
            db.execute("UPDATE logis_candidate.understanding_jobs SET version=version+1,status='running',attempts=attempts+1,lease_until=now()+interval '120 seconds',lease_token=%s WHERE id=%s",(token,row['id']))
            return {**row,'token':token}
    def complete(self,claim,result):
        with self.connect() as db:
            # Revalidate source visibility after inference, which runs outside the DB transaction.
            sources={r['id']:r['payload'].get('content','') for r in db.execute('SELECT id,payload FROM logis_candidate.sources WHERE project_id=%s AND deleted_at IS NULL',(claim['project_id'],))}
            result={**result,'items':[x for x in result['items'] if x['source_id'] in sources and x['quote'] in sources[x['source_id']]]}
            return bool(db.execute("UPDATE logis_candidate.understanding_jobs SET version=version+1,status='completed',result=%s,completed_at=now(),last_error=NULL,lease_until=NULL,lease_token=NULL WHERE id=%s AND lease_token=%s RETURNING id",(Jsonb(result),claim['id'],claim['token'])).fetchone())
    def fail(self,claim,error):
        with self.connect() as db:
            db.execute("UPDATE logis_candidate.understanding_jobs SET version=version+1,status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,last_error=%s,available_at=now()+make_interval(secs=>LEAST(300,attempts*10)),lease_until=NULL,lease_token=NULL WHERE id=%s AND lease_token=%s",(type(error).__name__,claim['id'],claim['token']))
    def process(self,claim):
        with self.connect() as db:
            rows=db.execute("SELECT m.source_id,m.role,m.content FROM logis_candidate.messages m JOIN logis_candidate.sources s ON s.id=m.source_id WHERE m.project_id=%s AND m.role='user' AND s.deleted_at IS NULL AND m.legacy_index<=(SELECT legacy_index FROM logis_candidate.messages WHERE id=%s) ORDER BY m.legacy_index DESC LIMIT 12",(claim['project_id'],claim['id'])).fetchall()
        return self.complete(claim,suggest(list(reversed(rows)),self.request_model))
    def once(self):
        if not self.slot.acquire(blocking=False):return False
        try:
            claim=self.claim()
            if not claim:return False
            try:self.process(claim)
            except Exception as error:self.fail(claim,error)
            return True
        finally:self.slot.release()
