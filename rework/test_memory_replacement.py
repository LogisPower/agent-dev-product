import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
import psycopg
client=TestClient(create_app(dsn,{'writer':{'projects':[first],'write':True},'reader':{'projects':[first]}}));headers={'Authorization':'Bearer writer'};ids=[];sources=[]
def post(path,body,key=None,role='writer'):return client.post(path,json=body,headers={'Authorization':'Bearer '+role,'Idempotency-Key':key or uuid.uuid4().hex})
try:
 with psycopg.connect(dsn) as db:
  for text in ['I prefer brief answers.','I now prefer detailed answers with examples.']:
   source='replace-test-'+uuid.uuid4().hex;sources.append(source)
   db.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES(%s,%s,'test_fixture','test',%s)",(source,first,Jsonb({'content':text})))
 for i,text in enumerate(['I prefer brief answers.','I now prefer detailed answers with examples.','I now prefer detailed answers with examples.']):
  response=post('/api/projects/'+first+'/objects',{'kind':'goals' if i==2 else 'preferences','title':text,'source_id':sources[min(i,1)],'quote':text});assert response.status_code==200,response.text;ids.append(response.json()['id'])
 old,new,goal=ids;confirm={'expected_version':1,'title':'Prefer brief answers','status':'confirmed'}
 assert client.patch('/api/projects/'+first+'/objects/'+old,json=confirm,headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==200
 url='/api/projects/'+first+'/memory/'+old+'/replace';body={'replacement_id':new,'expected_version':2,'replacement_version':1}
 assert client.post(url,json=body).status_code==401
 assert post(url,body,role='reader').status_code==403
 assert post('/api/projects/'+second+'/memory/'+old+'/replace',body).status_code==404
 assert post(url,{**body,'replacement_id':'missing'}).status_code==404
 assert post(url,{**body,'replacement_id':old}).status_code==422
 assert post(url,{**body,'replacement_id':goal}).status_code==422
 assert post(url,{**body,'expected_version':1}).status_code==409
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET revision=2 WHERE id=%s',(sources[1],))
 assert post(url,body).status_code==409
 with psycopg.connect(dsn) as db:
  assert db.execute('SELECT status FROM logis_candidate.objects WHERE id=%s',(old,)).fetchone()[0]=='confirmed'
  assert db.execute('SELECT status FROM logis_candidate.objects WHERE id=%s',(new,)).fetchone()[0]=='draft'
  db.execute('UPDATE logis_candidate.sources SET revision=1 WHERE id=%s',(sources[1],))
 key=uuid.uuid4().hex;replaced=post(url,body,key);assert replaced.status_code==200,replaced.text
 assert post(url,body,key).json()['replayed']
 assert post(url,{**body,'replacement_version':2},key).status_code==409
 assert post(url,body).status_code==409
 memory=client.get('/api/projects/'+first+'/memory',headers=headers).json();assert any(x['id']==new for x in memory) and not any(x['id']==old for x in memory)
 records={x['id']:x for x in client.get('/api/projects/'+first+'/objects',headers=headers).json()}
 assert records[old]['status']=='archived' and records[old]['replaced_by']==new and records[new]['replaces']==old
 # A current memory can be corrected again using a fresh draft, but a draft
 # with existing replacement history must not be reused to branch that history.
 extra=post('/api/projects/'+first+'/objects',{'kind':'preferences','title':'Fresh draft','source_id':sources[1],'quote':'I now prefer detailed answers with examples.'}).json()['id'];ids.append(extra)
 assert client.patch('/api/projects/'+first+'/objects/'+extra,json={'expected_version':1,'title':'Another confirmed preference','status':'confirmed'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==200
 assert client.patch('/api/projects/'+first+'/objects/'+new,json={'expected_version':2,'title':'Detailed answers','status':'draft'},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==200
 assert post('/api/projects/'+first+'/memory/'+extra+'/replace',{'replacement_id':new,'expected_version':2,'replacement_version':3}).status_code==409
 assert client.patch('/api/projects/'+first+'/objects/'+old,json={**confirm,'expected_version':3},headers={**headers,'Idempotency-Key':uuid.uuid4().hex}).status_code==409
 with psycopg.connect(dsn) as db:
  assert db.execute("SELECT count(*) FROM logis_candidate.events WHERE object_id=%s AND event_type='memory.replaced'",(new,)).fetchone()[0]==1
  assert db.execute("SELECT count(*) FROM logis_candidate.relationships WHERE from_id=%s AND to_id=%s AND relation='supersedes'",(new,old)).fetchone()[0]==1
 print('PASS: scoped atomic replacement, source/version/type checks, replay, predecessor history, current-memory retrieval and resurrection prevention')
finally:
 with psycopg.connect(dsn) as db:
  db.execute("SELECT pg_advisory_xact_lock(hashtext('logis-activity-feed'))")
  for table in ['activity_projection','consumer_receipts','outbox','operation_receipts']:
   db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id IN (SELECT event_id FROM logis_candidate.events WHERE object_id=ANY(%s))',(ids,))
  db.execute('DELETE FROM logis_candidate.events WHERE object_id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.relationships WHERE from_id=ANY(%s) OR to_id=ANY(%s)',(ids,ids));db.execute('DELETE FROM logis_candidate.evidence WHERE object_id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.objects WHERE id=ANY(%s)',(ids,));db.execute('DELETE FROM logis_candidate.sources WHERE id=ANY(%s)',(sources,))
