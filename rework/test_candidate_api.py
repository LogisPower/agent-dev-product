import sys,json,secrets,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
import psycopg
from fastapi.testclient import TestClient
from candidate_api import create_app
ROOT=Path(__file__).parent
connection=None
dsn=os.environ.get('LOGIS_TEST_DSN')
if dsn:connection=psycopg.connect(dsn)
for folder in ROOT.glob('postgres-restore-*'):
    if connection is not None:break
    pid=folder/'postmaster.pid'
    if not pid.exists():continue
    port=int(pid.read_text().splitlines()[3]);dsn=f'host=127.0.0.1 port={port} user=logis_restore dbname=postgres connect_timeout=2'
    try:
        connection=psycopg.connect(dsn);break
    except psycopg.Error:continue
if not connection:raise RuntimeError('No isolated restore cluster is available')
with connection:
    directory=connection.execute('SHOW data_directory').fetchone()[0]
    if '/rework/postgres-restore-' not in directory.replace('\\','/').lower():raise RuntimeError('Refusing non-isolated test database')
    rows=connection.execute('select id from logis_candidate.projects order by id limit 2').fetchall()
connection.close()
first,second=[row[0] for row in rows];token=secrets.token_urlsafe(32)
client=TestClient(create_app(dsn,{token:{'projects':[first]}}));headers={'Authorization':'Bearer '+token}
assert client.get('/api/projects').status_code==401
assert client.get('/api/projects',headers={'Authorization':'Bearer wrong'}).status_code==401
assert [x['id'] for x in client.get('/api/projects',headers=headers).json()]==[first]
assert client.get('/api/projects/'+first+'/messages',headers=headers).status_code==200
assert client.get('/api/projects/'+second+'/messages',headers=headers).status_code==404
assert client.get('/api/projects/'+second+'/objects',headers=headers).status_code==404
assert client.post('/api/projects',headers=headers,json={}).status_code==405
report={'verified':True,'checks':['missing credential rejected','invalid credential rejected','project list filtered','allowed messages readable','other project messages denied','other project objects denied','writes unavailable'],'productionModified':False}
(ROOT/'candidate-api-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
