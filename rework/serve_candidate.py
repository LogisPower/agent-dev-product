import sys,json,secrets
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'deps'))
import psycopg,uvicorn
from candidate_api import create_app
connection=None
for folder in ROOT.glob('postgres-restore-*'):
    pid=folder/'postmaster.pid'
    if not pid.exists():continue
    port=int(pid.read_text().splitlines()[3]);dsn=f'host=127.0.0.1 port={port} user=logis_restore dbname=postgres connect_timeout=2'
    try:connection=psycopg.connect(dsn);break
    except psycopg.Error:continue
if connection is None:raise RuntimeError('No isolated restore cluster running')
with connection:projects=[row[0] for row in connection.execute('select id from logis_candidate.projects')]
connection.close();access=ROOT/'preview-access.json';token=json.loads(access.read_text())['token'] if access.exists() else secrets.token_urlsafe(32)
(ROOT/'preview-access.json').write_text(json.dumps({'token':token}))
app=create_app(dsn,{token:{'projects':projects,'write':True}},run_worker=True)
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8092)
