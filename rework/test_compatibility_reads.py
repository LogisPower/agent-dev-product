import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from test_candidate_api import dsn,first,second
from candidate_api import create_app
from fastapi.testclient import TestClient
import psycopg
client=TestClient(create_app(dsn,{'reader':{'projects':[first]}}));headers={'Authorization':'Bearer reader'}
state=client.get('/api/state',params={'id':first},headers=headers)
assert state.status_code==200,state.text
assert state.json()['capabilities']['generation'] is False
canonical=client.get('/api/projects/'+first+'/messages',headers=headers).json()
assert state.json()['history']==canonical
assert client.get('/api/state',params={'id':second},headers=headers).status_code==404
for view in ['tasks','decisions','cases','routines','pipelines','skills','org','conference','agents']:
 response=client.get('/api/workspace',params={'view':view},headers=headers)
 assert response.status_code==200
 assert all(x['project_id']==first for x in response.json())
assert client.get('/api/workspace',params={'view':'settings'},headers=headers).status_code==501
assert len(client.get('/api/projects',params={'q':'no such project 987654321'},headers=headers).json())==0
assert client.get('/api/state',params={'id':first}).status_code==401
print('PASS: compatible snapshot reads, canonical history parity, project-scoped workspace views, search, authentication and explicit unavailable features')
