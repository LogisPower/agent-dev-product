import sys,json,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from conversation_understanding import suggest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
import psycopg
source='memory-test-'+uuid.uuid4().hex;ids=[];content='I prefer concise answers. My goal is to build accessible calendar tools.'
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True},'reader':{'projects':[first]}}));headers={'Authorization':'Bearer writer'}
url='/api/projects/'+first+'/objects';memory='/api/projects/'+first+'/memory'
try:
 with psycopg.connect(dsn) as db:db.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES(%s,%s,'test_fixture','test',%s)",(source,first,Jsonb({'content':content})))
 items=[{'kind':'preferences','title':'Prefer concise answers','source_id':source,'quote':'I prefer concise answers'},{'kind':'goals','title':'Build accessible calendar tools','source_id':source,'quote':'My goal is to build accessible calendar tools'}]
 result=suggest([{'role':'user','source_id':source,'content':content}],lambda _:json.dumps({'items':items}));assert len(result['items'])==2
 assert client.get(memory).status_code==401
 assert client.get('/api/projects/'+second+'/memory',headers=headers).status_code==404
 assert client.post(url,json={'kind':'preferences','title':'No evidence'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==422
 assert client.post(url,json={**items[0],'status':'open'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==422
 for item in items:
  saved=client.post(url,json=item,headers={**headers,'Idempotency-Key':uuid.uuid4().hex});assert saved.status_code==200,saved.text
  ids.append(saved.json()['id'])
 assert not any(x['id'] in ids for x in client.get(memory,headers=headers).json())
 task=client.post(url,json={'kind':'tasks','title':'Task status policy test'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).json()['id'];ids.append(task)
 assert client.patch(url+'/'+task,json={'expected_version':1,'title':'Task status policy test','status':'confirmed'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==422
 confirm={'expected_version':1,'title':items[0]['title'],'detail':'','status':'confirmed'}
 h={**headers,'Idempotency-Key':uuid.uuid4().hex};patch=url+'/'+ids[0]
 assert client.patch(patch,json=confirm,headers={**h,'Authorization':'Bearer reader'}).status_code==403
 confirmed=client.patch(patch,json=confirm,headers=h);assert confirmed.status_code==200,confirmed.text
 assert client.patch(patch,json=confirm,headers=h).json()['replayed']
 assert any(x['id']==ids[0] for x in client.get(memory,headers=headers).json())
 archived=client.patch(patch,json={**confirm,'expected_version':2,'status':'archived'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex});assert archived.status_code==200
 assert not any(x['id'] in ids for x in client.get(memory,headers=headers).json())
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET revision=revision+1 WHERE id=%s',(source,))
 stale=client.patch(url+'/'+ids[1],json={**confirm,'title':items[1]['title']},headers={**headers,'Idempotency-Key':uuid.uuid4().hex});assert stale.status_code==409
 assert not any(x['id'] in ids[:2] for x in client.get(url,headers=headers).json())
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET deleted_at=now() WHERE id=%s',(source,))
 assert not any(x['id'] in ids for x in client.get(memory,headers=headers).json())
 print('PASS: preference/goal extraction, evidence-required drafts, explicit scoped confirmation, replay, archive, changed-source exclusion and deleted-source privacy')
finally:
 with psycopg.connect(dsn) as db:
  db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
  for table in ['activity_projection','consumer_receipts','outbox','operation_receipts']:
   db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=ANY(%s))',(ids,))
  db.execute('DELETE FROM logis_candidate.events WHERE object_id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.evidence WHERE object_id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.objects WHERE id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.sources WHERE id=%s',(source,))
