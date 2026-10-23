import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from outbox_worker import Worker
from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
ids=[];worker=Worker(dsn)
try:
 with psycopg.connect(dsn) as db:
  db.execute((Path(__file__).parent/'003_event_feed.sql').read_text())
  cursor=db.execute('SELECT coalesce(max(sequence),0) FROM logis_candidate.activity_projection').fetchone()[0]
 for project in [first,second,first]:
  identifier=uuid.uuid4().hex;ids.append(identifier)
  with psycopg.connect(dsn) as db:
   db.execute('INSERT INTO logis_candidate.events(event_id,event_type,object_id,actor_id,correlation_id,permissions_scope,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)',(identifier,'test.updated','test-object','test',identifier,project,Jsonb({'version':1})))
   db.execute('INSERT INTO logis_candidate.outbox(event_id) VALUES(%s)',(identifier,))
  claim=worker.claim(identifier);worker.project(claim);worker.acknowledge(claim)
 client=TestClient(create_app(dsn,{'reader':{'projects':[first]}}));headers={'Authorization':'Bearer reader'}
 assert client.get('/api/events').status_code==401
 page=client.get('/api/events',params={'after':cursor,'limit':1},headers=headers).json()
 assert len(page['events'])==1 and page['has_more'];assert page['events'][0]['event_id']==ids[0]
 nextpage=client.get('/api/events',params={'after':page['next_cursor']},headers=headers).json()
 assert [x['event_id'] for x in nextpage['events']]==[ids[2]]
 assert client.get('/api/events',params={'after':nextpage['next_cursor']},headers=headers).json()['events']==[]
 assert client.get('/api/events',params={'project':second},headers=headers).status_code==404
 assert client.get('/api/events',params={'after':-1},headers=headers).status_code==422
 print('PASS: scoped feed, pagination, reconnect cursor, no duplicate catch-up, unauthorized project denial, invalid cursor rejection')
finally:
 with psycopg.connect(dsn) as db:
  for table in ['activity_projection','consumer_receipts','outbox','events']:db.execute('DELETE FROM logis_candidate.'+table+' WHERE event_id=ANY(%s)',(ids,))
