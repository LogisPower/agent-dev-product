import uuid,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first
from outbox_worker import Worker
import psycopg
from psycopg.types.json import Jsonb
worker=Worker(dsn,max_attempts=2);identifiers=[]
def event():
 identifier=uuid.uuid4().hex;identifiers.append(identifier)
 with psycopg.connect(dsn) as db:
  db.execute('INSERT INTO logis_candidate.events(event_id,event_type,object_id,actor_id,correlation_id,permissions_scope,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)',(identifier,'test.updated','test-object','test',identifier,first,Jsonb({'version':1})))
  db.execute('INSERT INTO logis_candidate.outbox(event_id) VALUES(%s)',(identifier,))
 return identifier
try:
 with psycopg.connect(dsn) as db:db.execute((Path(__file__).parent/'002_delivery.sql').read_text())
 identifier=event();claim=worker.claim(identifier);assert claim
 assert worker.claim(identifier) is None
 assert worker.project(claim)
 # Simulate consumer commit followed by crash before acknowledgment.
 with psycopg.connect(dsn) as db:db.execute("UPDATE logis_candidate.outbox SET lease_until=now()-interval '1 second' WHERE event_id=%s",(identifier,))
 replacement=worker.claim(identifier);assert replacement and not worker.project(replacement)
 assert not worker.acknowledge(claim);assert worker.acknowledge(replacement)
 identifier2=event();claim2=worker.claim(identifier2);worker.fail(claim2,'simulated error')
 with psycopg.connect(dsn) as db:
  state=db.execute('SELECT attempts,dead_letter,last_error,available_at>now() FROM logis_candidate.outbox WHERE event_id=%s',(identifier2,)).fetchone();assert state==(1,False,'simulated error',True)
  db.execute("UPDATE logis_candidate.outbox SET available_at=now()-interval '1 second' WHERE event_id=%s",(identifier2,))
 worker.fail(worker.claim(identifier2),'repeat failure');assert worker.claim(identifier2) is None
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT dead_letter FROM logis_candidate.outbox WHERE event_id=%s',(identifier2,)).fetchone()[0]
  assert db.execute('SELECT count(*) FROM logis_candidate.activity_projection WHERE event_id=%s',(identifier,)).fetchone()[0]==1
 print('PASS: exclusive lease, crash recovery, duplicate consumption, stale acknowledgement, retry delay, dead-letter isolation')
finally:
 with psycopg.connect(dsn) as db:
  for table in ['activity_projection','consumer_receipts','outbox','events']:db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id=ANY(%s)',(identifiers,))
