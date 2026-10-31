import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True},'reader':{'projects':[first]}}));headers={'Authorization':'Bearer writer','Idempotency-Key':uuid.uuid4().hex}
url='/api/projects/'+first+'/objects';ids=[];source='test-'+uuid.uuid4().hex
try:
 with psycopg.connect(dsn) as db:db.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES(%s,%s,'test','test',%s)",(source,first,Jsonb({'content':'Build the candidate test screen'})))
 body={'kind':'tasks','title':'Candidate API creation test','source_id':source,'quote':'Build the candidate test screen'}
 assert client.post(url,json=body,headers={**headers,'Authorization':'Bearer reader'}).status_code==403
 assert client.post('/api/projects/'+second+'/objects',json=body,headers=headers).status_code==404
 created=client.post(url,json=body,headers=headers);assert created.status_code==200,created.text
 identifier=created.json()['id'];ids.append(identifier)
 replay=client.post(url,json=body,headers=headers);assert replay.json()['id']==identifier and replay.json()['replayed']
 assert client.post(url,json={**body,'title':'Changed'},headers=headers).status_code==409
 invalid=client.post(url,json={**body,'quote':'Invented source content'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex});assert invalid.status_code==422
 decision=client.post(url,json={'kind':'decisions','title':'Synthetic candidate decision'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex});assert decision.status_code==200;ids.append(decision.json()['id'])
 assert client.get('/api/objects/'+identifier+'/evidence',headers=headers).json()[0]['quote']==body['quote']
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT count(*) FROM logis_candidate.events WHERE object_id=%s',(identifier,)).fetchone()[0]==1
 print('PASS: task/decision creation, read-only/project denial, replay deduplication, conflicting-key rejection, quote validation, linked evidence and one event')
finally:
 with psycopg.connect(dsn) as db:
  db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
  for table in ['activity_projection','consumer_receipts','outbox','operation_receipts']:
   db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=ANY(%s))',(ids,))
  db.execute('DELETE FROM logis_candidate.events WHERE object_id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.evidence WHERE object_id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.objects WHERE id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.sources WHERE id=%s',(source,))
