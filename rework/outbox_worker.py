"""Leased at-least-once delivery with an idempotent transactional DB consumer."""
import uuid
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'deps'))
import psycopg
from psycopg.rows import dict_row
class Worker:
    def __init__(self,dsn,max_attempts=5):self.dsn=dsn;self.max_attempts=max_attempts
    def connect(self):
        db=psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=3,options="-c statement_timeout=5000 -c lock_timeout=2000")
        directory=db.execute('show data_directory').fetchone()['data_directory']
        if '/rework/postgres-restore-' not in directory.replace('\\','/').lower():db.close();raise RuntimeError('Refusing non-isolated database')
        return db
    def claim(self,event_id=None):
        token=uuid.uuid4().hex
        with self.connect() as db:
            row=db.execute("SELECT * FROM logis_candidate.outbox WHERE delivered_at IS NULL AND NOT dead_letter AND available_at<=now() AND (lease_until IS NULL OR lease_until<now()) AND (%s::text IS NULL OR event_id=%s) ORDER BY available_at,event_id FOR UPDATE SKIP LOCKED LIMIT 1",(event_id,event_id)).fetchone()
            if not row:return None
            db.execute("UPDATE logis_candidate.outbox SET lease_until=now()+interval '60 seconds',lease_token=%s,attempts=attempts+1 WHERE event_id=%s",(token,row['event_id']))
            return {'event_id':row['event_id'],'token':token}
    def project(self,claim):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
            event=db.execute('SELECT * FROM logis_candidate.events WHERE event_id=%s',(claim['event_id'],)).fetchone()
            receipt=db.execute("INSERT INTO logis_candidate.consumer_receipts(consumer,event_id) VALUES('workspace_projection',%s) ON CONFLICT DO NOTHING RETURNING event_id",(claim['event_id'],)).fetchone()
            if not receipt:return False
            db.execute('INSERT INTO logis_candidate.activity_projection(event_id,project_id,object_id,event_type,record_version) VALUES(%s,%s,%s,%s,%s)',(event['event_id'],event['permissions_scope'],event['object_id'],event['event_type'],event['payload']['version']))
            return True
    def acknowledge(self,claim):
        with self.connect() as db:
            row=db.execute('UPDATE logis_candidate.outbox SET delivered_at=now(),lease_until=NULL,lease_token=NULL,last_error=NULL WHERE event_id=%s AND lease_token=%s RETURNING event_id',(claim['event_id'],claim['token'])).fetchone()
            return bool(row)
    def fail(self,claim,error):
        with self.connect() as db:
            db.execute("UPDATE logis_candidate.outbox SET dead_letter=(attempts>=%s),available_at=now()+make_interval(secs=>LEAST(300,power(2,LEAST(attempts,8))::integer)),last_error=%s,lease_until=NULL,lease_token=NULL WHERE event_id=%s AND lease_token=%s",(self.max_attempts,str(error)[:1000],claim['event_id'],claim['token']))
    def once(self):
        claim=self.claim()
        if not claim:return False
        try:self.project(claim);self.acknowledge(claim)
        except Exception as error:self.fail(claim,error)
        return True
