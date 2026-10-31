import sys,uuid,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from fastapi.testclient import TestClient
import psycopg
identifier='test-'+uuid.uuid4().hex;key=uuid.uuid4().hex
with psycopg.connect(dsn) as db:db.execute("INSERT INTO logis_candidate.objects(id,kind,project_id,status,payload) VALUES(%s,'tasks',%s,'open','{}')",(identifier,first))
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True,'actor':'test-writer'},'reader':{'projects':[first]}}))
url='/api/projects/'+first+'/objects/'+identifier
body={'expected_version':1,'status':'done','title':'Verified update','detail':'test'}
headers={'Authorization':'Bearer writer','Idempotency-Key':key}
try:
 assert client.patch(url,json=body,headers={**headers,'Authorization':'Bearer reader'}).status_code==403
 assert client.patch('/api/projects/'+second+'/objects/'+identifier,json=body,headers=headers).status_code==404
 response=client.patch(url,json=body,headers=headers);assert response.status_code==200,response.text
 repeated=client.patch(url,json=body,headers=headers);assert repeated.json()['event_id']==response.json()['event_id'] and repeated.json()['replayed']
 assert client.patch(url,json={**body,'title':'Different'},headers=headers).status_code==409
 assert client.patch(url,json=body,headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==409
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT version FROM logis_candidate.objects WHERE id=%s',(identifier,)).fetchone()[0]==2
  assert db.execute('SELECT count(*) FROM logis_candidate.events WHERE object_id=%s',(identifier,)).fetchone()[0]==1
  assert db.execute('SELECT count(*) FROM logis_candidate.outbox WHERE event_id=%s',(response.json()['event_id'],)).fetchone()[0]==1
 print('PASS: scoped writes, read-only denial, replay deduplication, conflicting-key denial, stale-write rollback, single transactional event and outbox entry')
finally:
 with psycopg.connect(dsn) as db:
  db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
  db.execute('DELETE FROM logis_candidate.activity_projection WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=%s)',(identifier,))
  db.execute('DELETE FROM logis_candidate.consumer_receipts WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=%s)',(identifier,))
  db.execute('DELETE FROM logis_candidate.operation_receipts WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=%s)',(identifier,))
  db.execute('DELETE FROM logis_candidate.outbox WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=%s)',(identifier,))
  db.execute('DELETE FROM logis_candidate.events WHERE object_id=%s',(identifier,));db.execute('DELETE FROM logis_candidate.objects WHERE id=%s',(identifier,))
