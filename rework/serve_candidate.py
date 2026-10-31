import sys,json,secrets,os
from pathlib import Path
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'deps'))
sys.path.append(str(ROOT.parent/'runtime/agent-libs'))
import psycopg,uvicorn
from candidate_api import create_app
connection=None
for folder in ROOT.glob('postgres-restore-*'):
    pid=folder/'postmaster.pid'
    if not pid.exists():continue
    port=int(pid.read_text().splitlines()[3]);dsn=f'host=127.0.0.1 port={port} user=logis_restore dbname=postgres connect_timeout=2'
    try:
        candidate=psycopg.connect(dsn)
        ready=candidate.execute("SELECT to_regclass('logis_candidate.understanding_jobs'),to_regclass('logis_candidate.outbox')").fetchone()
        candidate.rollback()
        if not all(ready):candidate.close();continue
        connection=candidate;break
    except psycopg.Error:continue
if connection is None:raise RuntimeError('No isolated restore cluster running')
with connection:
    projects=[row[0] for row in connection.execute('select id from logis_candidate.projects')]
    connection.execute("UPDATE logis_candidate.runs SET status='interrupted',payload=payload || '{\"notice\":\"Previous process stopped before a saved reply; no automatic retry.\"}'::jsonb WHERE agent_id IN ('local-chat','local-build','hindsight-capture','public-research','document-answer') AND status IN ('running','dispatching') AND NOT (payload ? '_dispatch')")
connection.close();access=ROOT/'preview-access.json';token=json.loads(access.read_text())['token'] if access.exists() else secrets.token_urlsafe(32)
(ROOT/'preview-access.json').write_text(json.dumps({'token':token}))
from setup_scope import ScopeResolver,database_projects
setup_resolver=ScopeResolver(projects,ROOT,lambda:database_projects(dsn))
from optional_policy import PolicyCredentials
policy_credentials=PolicyCredentials({token:{'projects':projects,'write':True}},ROOT/'optional-tool-access.json',projects,setup_resolver.active)
app=create_app(dsn,policy_credentials,scope_refresh=setup_resolver.resolve,run_worker=True,background_chat=True,enable_research=True,device_store=Path(os.environ['LOCALAPPDATA'])/'LogisRework/auth/device-sessions.sqlite')
from candidate_chat import bounded_chat
from runtime_cpu_setup import configure
configure(app,ROOT,bounded_chat)
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8092)
