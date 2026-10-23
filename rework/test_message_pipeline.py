import sys,json,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from understanding_worker import UnderstandingWorker
from fastapi.testclient import TestClient
import psycopg
ids=[];sources=[];objects=[]
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True},'reader':{'projects':[first]}}))
headers={'Authorization':'Bearer writer','Idempotency-Key':uuid.uuid4().hex};url='/api/projects/'+first+'/messages'
content='Please build a project calendar page.'
def model(messages):
 data=json.loads(messages[-1]['content']);source=data[-1]['source_id']
 return json.dumps({'items':[{'kind':'tasks','title':'Build project calendar','source_id':source,'quote':content}]})
try:
 assert client.post(url,json={'content':content}).status_code==401
 assert client.post(url,json={'content':content},headers={**headers,'Authorization':'Bearer reader'}).status_code==403
 assert client.post('/api/projects/'+second+'/messages',json={'content':content},headers=headers).status_code==404
 assert client.post(url,json={'content':content,'role':'assistant'},headers=headers).status_code==422
 assert client.post(url,json={'content':'  '},headers=headers).status_code==422
 response=client.post(url,json={'content':content},headers=headers);assert response.status_code==200,response.text
 identifier=response.json()['id'];ids.append(identifier);sources.append('message-'+identifier)
 assert client.post(url,json={'content':content},headers=headers).json()['replayed']
 assert client.post(url,json={'content':'Different message'},headers=headers).status_code==409
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT count(*) FROM logis_candidate.understanding_jobs WHERE id=%s',(identifier,)).fetchone()[0]==1
  assert db.execute('SELECT count(*) FROM logis_candidate.events WHERE object_id=%s',(identifier,)).fetchone()[0]==1
 worker=UnderstandingWorker(dsn,model);claim=worker.claim(identifier);assert claim
 assert UnderstandingWorker(dsn,model).claim(identifier) is None
 with psycopg.connect(dsn) as db:db.execute("UPDATE logis_candidate.understanding_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",(identifier,))
 restarted=UnderstandingWorker(dsn,model);new_claim=restarted.claim(identifier);assert new_claim
 assert not worker.complete(claim,{'items':[]})
 assert restarted.process(new_claim)
 assert restarted.claim(identifier) is None
 snapshot=client.get('/api/state?id='+first,headers=headers).json();assert snapshot['history'][-1]['content']==content
 jobs=client.get('/api/projects/'+first+'/understanding/jobs',headers=headers).json();job=next(x for x in jobs if x['id']==identifier)
 assert job['status']=='completed' and job['result']['items'][0]['quote']==content
 assert client.get('/api/projects/'+second+'/understanding/jobs',headers=headers).status_code==404
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT count(*) FROM logis_candidate.evidence WHERE source_id=%s',(sources[0],)).fetchone()[0]==0
 item=job['result']['items'][0]
 body={k:item[k] for k in ['kind','title','source_id','quote','status']}
 saved=client.post('/api/projects/'+first+'/objects',json=body,headers={**headers,'Idempotency-Key':'extraction-'+item['suggestion_key']});assert saved.status_code==200
 objects.append(saved.json()['id'])
 assert next(x for x in client.get('/api/projects/'+first+'/understanding/jobs',headers=headers).json() if x['id']==identifier)['result']['items'][0]['saved']
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET deleted_at=now() WHERE id=%s',(sources[0],))
 assert next(x for x in client.get('/api/projects/'+first+'/understanding/jobs',headers=headers).json() if x['id']==identifier)['result']['items']==[]
 failed=client.post(url,json={'content':content},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).json()['id'];ids.append(failed);sources.append('message-'+failed)
 for attempt in range(3):
  claim=worker.claim(failed);assert claim
  worker.fail(claim,ValueError('private text must never reach job errors'))
  with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.understanding_jobs SET available_at=now() WHERE id=%s',(failed,))
 assert worker.claim(failed) is None
 with psycopg.connect(dsn) as db:
  row=db.execute('SELECT status,last_error FROM logis_candidate.understanding_jobs WHERE id=%s',(failed,)).fetchone();assert row==('failed','ValueError')
 print('PASS: atomic message/job/event intake, scoped roles, replay, restart lease recovery, stale completion rejection, durable suggestions, deleted evidence exclusion and bounded redacted retries')
finally:
 with psycopg.connect(dsn) as db:
  db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
  for table in ['activity_projection','consumer_receipts','outbox','operation_receipts']:
   db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=ANY(%s))',(ids+objects,))
  db.execute('DELETE FROM logis_candidate.events WHERE object_id=ANY(%s)',(ids+objects,))
  db.execute('DELETE FROM logis_candidate.evidence WHERE object_id=ANY(%s)',(objects,))
  db.execute('DELETE FROM logis_candidate.objects WHERE id=ANY(%s)',(objects,))
  db.execute('DELETE FROM logis_candidate.understanding_jobs WHERE id=ANY(%s)',(ids,))
  db.execute('DELETE FROM logis_candidate.messages WHERE id=ANY(%s)',(ids,))
  db.execute('DELETE FROM logis_candidate.sources WHERE id=ANY(%s)',(sources,))
