import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from fastapi.testclient import TestClient
from understanding_worker import UnderstandingWorker
import psycopg
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True},'reader':{'projects':[first]}}));headers={'Authorization':'Bearer writer','Idempotency-Key':uuid.uuid4().hex}
identifier=None
try:
 identifier=client.post('/api/projects/'+first+'/messages',headers=headers,json={'content':'Please add a keyboard shortcut guide.'}).json()['id']
 worker=UnderstandingWorker(dsn,lambda _: '{"items":[]}')
 claim=worker.claim(identifier);worker.fail(claim,ValueError('Sensitive content stays out of error state'))
 with psycopg.connect(dsn) as db:db.execute("UPDATE logis_candidate.understanding_jobs SET status='failed',attempts=3,version=version+1 WHERE id=%s",(identifier,))
 jobs=client.get('/api/projects/'+first+'/understanding/jobs',headers=headers).json();job=next(x for x in jobs if x['id']==identifier)
 assert job['message_preview']=='Please add a keyboard shortcut guide.' and job['last_error']=='ValueError'
 url='/api/projects/'+first+'/understanding/jobs/'+identifier+'/retry';body={'expected_version':job['version']}
 h={**headers,'Idempotency-Key':uuid.uuid4().hex}
 assert client.post(url,json=body).status_code==401
 assert client.post(url,json=body,headers={**h,'Authorization':'Bearer reader'}).status_code==403
 assert client.post('/api/projects/'+second+'/understanding/jobs/'+identifier+'/retry',json=body,headers=h).status_code==404
 assert client.post(url,json={'expected_version':1},headers=h).status_code==409
 assert client.post(url,json=body,headers=h).status_code==200
 assert client.post(url,json=body,headers=h).json()['replayed']
 assert client.post(url,json={'expected_version':body['expected_version']+1},headers=h).status_code==409
 assert client.post(url,json=body,headers={**h,'Idempotency-Key':uuid.uuid4().hex}).status_code==409
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT status,attempts,result,last_error FROM logis_candidate.understanding_jobs WHERE id=%s',(identifier,)).fetchone()==('pending',0,None,None)
  assert db.execute("SELECT count(*) FROM logis_candidate.events WHERE object_id=%s AND event_type='understanding.retried'",(identifier,)).fetchone()[0]==1
 fresh=UnderstandingWorker(dsn,lambda _: '{"items":[]}');assert fresh.process(fresh.claim(identifier))
 assert client.post(url,json=body,headers={**h,'Idempotency-Key':uuid.uuid4().hex}).status_code==409
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET deleted_at=now() WHERE id=%s',('message-'+identifier,))
 assert not any(x['id']==identifier for x in client.get('/api/projects/'+first+'/understanding/jobs',headers=headers).json())
 assert client.post(url,json=body,headers={**h,'Idempotency-Key':uuid.uuid4().hex}).status_code==404
 print('PASS: scoped retry, stale-version rejection, replay deduplication, atomic reset/event, worker recovery, completed-job denial and deleted-message privacy')
finally:
 if identifier:
  with psycopg.connect(dsn) as db:
   db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
   for table in ['activity_projection','consumer_receipts','outbox','operation_receipts']:
    db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=%s)',(identifier,))
   db.execute('DELETE FROM logis_candidate.events WHERE object_id=%s',(identifier,));db.execute('DELETE FROM logis_candidate.understanding_jobs WHERE id=%s',(identifier,));db.execute('DELETE FROM logis_candidate.messages WHERE id=%s',(identifier,));db.execute('DELETE FROM logis_candidate.sources WHERE id=%s',('message-'+identifier,))
