import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
identifier='source-test-'+uuid.uuid4().hex;obj=identifier+'-task'
client=TestClient(create_app(dsn,{'reader':{'projects':[first]},'other':{'projects':[second]}}));headers={'Authorization':'Bearer reader'}
try:
 with psycopg.connect(dsn) as db:
  db.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES(%s,%s,'message','test',%s)",(identifier,first,Jsonb({'content':'Candidate evidence source test'})))
  db.execute("INSERT INTO logis_candidate.objects(id,kind,project_id,status,payload) VALUES(%s,'tasks',%s,'draft','{}')",(obj,first))
  db.execute('INSERT INTO logis_candidate.evidence VALUES(%s,%s,1,%s,true)',(obj,identifier,'Candidate evidence'))
 assert client.get('/api/sources/'+identifier,headers=headers).status_code==200
 assert client.get('/api/sources/'+identifier,headers={'Authorization':'Bearer other'}).status_code==404
 assert client.get('/api/objects/'+obj+'/evidence',headers=headers).json()[0]['source_id']==identifier
 assert client.get('/api/objects/'+obj+'/evidence',headers={'Authorization':'Bearer other'}).status_code==404
 with psycopg.connect(dsn) as db:db.execute('UPDATE logis_candidate.sources SET deleted_at=now() WHERE id=%s',(identifier,))
 assert client.get('/api/sources/'+identifier,headers=headers).status_code==404
 assert client.get('/api/objects/'+obj+'/evidence',headers=headers).json()==[]
 print('PASS: source access, evidence linkage, project isolation and deleted-source exclusion')
finally:
 with psycopg.connect(dsn) as db:
  db.execute('DELETE FROM logis_candidate.evidence WHERE object_id=%s',(obj,));db.execute('DELETE FROM logis_candidate.objects WHERE id=%s',(obj,));db.execute('DELETE FROM logis_candidate.sources WHERE id=%s',(identifier,))
