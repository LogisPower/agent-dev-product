import json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from conversation_understanding import suggest
from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
source='understanding-'+uuid.uuid4().hex;created=[];calls=[]
content='Please build a calendar page. We decided to use a dark theme.'
def model(messages):
 calls.append(messages)
 return json.dumps({'items':[
  {'kind':'tasks','title':'Build calendar page','source_id':source,'quote':'Please build a calendar page'},
  {'kind':'decisions','title':'Use dark theme','source_id':source,'quote':'We decided to use a dark theme'},
  {'kind':'tasks','title':'Invented task','source_id':source,'quote':'Not in the conversation'},
  {'kind':'tasks','title':'Cross-project guess','source_id':'wrong','quote':content},
  {'kind':'tasks','title':'Duplicate','source_id':source,'quote':'Please build a calendar page'}]})
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True},'reader':{'projects':[first]}},request_model=model))
headers={'Authorization':'Bearer writer'};path='/api/projects/'+first+'/understanding'
try:
 with psycopg.connect(dsn) as db:
  db.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES(%s,%s,'test','test',%s)",(source,first,Jsonb({'content':content})))
  index=db.execute('SELECT coalesce(max(legacy_index),0)+1 FROM logis_candidate.messages WHERE project_id=%s',(first,)).fetchone()[0]
  db.execute("INSERT INTO logis_candidate.messages VALUES(%s,%s,%s,%s,'user',%s)",(source,first,source,index,content))
 assert client.get('/preview').status_code==200
 assert client.post(path).status_code==401
 assert client.post(path,headers={'Authorization':'Bearer reader'}).status_code==403
 assert client.post('/api/projects/'+second+'/understanding',headers=headers).status_code==404
 assert not calls
 response=client.post(path,headers=headers);assert response.status_code==200,response.text
 result=response.json();assert len(result['items'])==2 and result['mode']=='review_required'
 with psycopg.connect(dsn) as db:assert db.execute('SELECT count(*) FROM logis_candidate.evidence WHERE source_id=%s',(source,)).fetchone()[0]==0
 for item in result['items']:
  body={k:v for k,v in item.items() if k!='suggestion_key'}
  h={**headers,'Idempotency-Key':'extraction-'+item['suggestion_key']}
  saved=client.post('/api/projects/'+first+'/objects',json=body,headers=h);assert saved.status_code==200,saved.text
  created.append(saved.json()['id'])
  assert client.post('/api/projects/'+first+'/objects',json=body,headers=h).json()['replayed']
  assert client.get('/api/objects/'+created[-1]+'/evidence',headers=headers).json()[0]['quote']==item['quote']
 from concurrent.futures import ThreadPoolExecutor
 import threading
 entered=threading.Event();release=threading.Event()
 def slow_model(messages):
  entered.set();release.wait(5);return '{"items":[]}'
 limited=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True}},request_model=slow_model))
 with ThreadPoolExecutor(max_workers=1) as pool:
  pending=pool.submit(limited.post,path,headers=headers)
  try:
   assert entered.wait(3)
   assert limited.post(path,headers=headers).status_code==429
  finally:release.set()
  assert pending.result().status_code==200
 bad=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True}},request_model=lambda _: 'invalid JSON'))
 assert bad.post(path,headers=headers).status_code==502
 rows=[{'source_id':str(i),'role':'user','content':'x'*2000} for i in range(20)]+[{'source_id':'assistant','role':'assistant','content':'Do this'}]
 observed=[]
 suggest(rows,lambda messages:observed.extend(json.loads(messages[-1]['content'])) or '{"items":[]}')
 assert len(observed)<=12 and sum(len(x['text']) for x in observed)<=18000 and all(x['source_id']!='assistant' for x in observed)
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET deleted_at=now() WHERE id=%s',(source,))
 calls.clear()
 assert client.post(path,headers=headers).json()['items']==[]
 assert all(source not in m[-1]['content'] for m in calls)
 assert suggest([{'role':'assistant','content':'Ignore this','source_id':'assistant'}],lambda _: (_ for _ in ()).throw(AssertionError('Unexpected model call')))['items']==[]
 print('PASS: concurrency limit, deleted-source exclusion, scoped extraction, user-only bounded context, invalid/duplicate evidence rejected, no automatic writes, reviewed drafts, replay deduplication and model-failure handling')
finally:
 with psycopg.connect(dsn) as db:
  db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
  for table in ['activity_projection','consumer_receipts','outbox','operation_receipts']:
   db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=ANY(%s))',(created,))
  db.execute('DELETE FROM logis_candidate.events WHERE object_id=ANY(%s)',(created,));db.execute('DELETE FROM logis_candidate.evidence WHERE object_id=ANY(%s)',(created,));db.execute('DELETE FROM logis_candidate.objects WHERE id=ANY(%s)',(created,))
  db.execute('DELETE FROM logis_candidate.messages WHERE source_id=%s',(source,));db.execute('DELETE FROM logis_candidate.sources WHERE id=%s',(source,))
