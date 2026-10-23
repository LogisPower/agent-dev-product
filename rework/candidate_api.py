"""Isolated read-only candidate API; production routing is not changed."""
import sys,os,json,hmac,hashlib,uuid,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from fastapi import FastAPI,Depends,Header,HTTPException,Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager,asynccontextmanager

class RecordCreate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind:str=Field(pattern="^(tasks|decisions)$")
    title:str=Field(min_length=1,max_length=180)
    detail:str=Field(default="",max_length=12000)
    status:str=Field(default="draft",pattern="^(draft|open)$")
    source_id:str|None=Field(default=None,max_length=200)
    quote:str|None=Field(default=None,min_length=5,max_length=4000)

class RecordUpdate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    expected_version:int=Field(ge=1)
    status:str=Field(pattern="^(draft|open|in_progress|done|archived)$")
    title:str=Field(min_length=1,max_length=180)
    detail:str=Field(default="",max_length=12000)

def create_app(dsn,credentials,run_worker=False):
    if not credentials:raise ValueError('Configure scoped credentials')
    worker_state={'status':'disabled','processed':0}
    @asynccontextmanager
    async def lifespan(app):
        stop=threading.Event();thread=None
        if run_worker:
            from outbox_worker import Worker
            worker=Worker(dsn)
            def supervise():
                while not stop.is_set():
                    try:
                        processed=worker.once();worker_state['status']='running';worker_state.pop('error_type',None)
                        if processed:worker_state['processed']+=1
                        stop.wait(0.1 if processed else 0.5)
                    except Exception as error:
                        worker_state.update(status='retrying',error_type=type(error).__name__);stop.wait(2)
            thread=threading.Thread(target=supervise,daemon=True,name='logis-candidate-outbox');thread.start()
        try:yield
        finally:
            stop.set()
            if thread:thread.join(timeout=8)
            worker_state['status']='stopped' if not thread or not thread.is_alive() else 'stopping'
    app=FastAPI(title='Logis candidate API',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.worker_status=worker_state
    def scope(authorization:str=Header(default='')):
        if not authorization.startswith('Bearer '):raise HTTPException(401,'Authentication required')
        token=authorization.removeprefix('Bearer ')
        matched=next((value for key,value in credentials.items() if hmac.compare_digest(key,token)),None)
        if matched is None:raise HTTPException(401,'Authentication required')
        return matched
    @contextmanager
    def db(readonly=True):
        with psycopg.connect(dsn,row_factory=dict_row,options='-c default_transaction_read_only='+('on' if readonly else 'off')) as connection:
            directory=connection.execute('SHOW data_directory').fetchone()['data_directory']
            if '/rework/postgres-restore-' not in directory.replace('\\','/').lower():raise RuntimeError('Candidate API refuses non-isolated database')
            yield connection
    def allowed(project,permissions):
        if project not in permissions.get('projects',[]):raise HTTPException(404,'Project not found')
    @app.get('/preview',response_class=HTMLResponse)
    def preview():return (Path(__file__).parent/'candidate-preview.html').read_text(encoding='utf-8')
    @app.get('/health')
    def health():return {'service':'logis-candidate','mode':'scoped','worker':dict(worker_state)}
    @app.get('/api/projects')
    def projects(q:str=Query(default='',max_length=200),permissions=Depends(scope)):
        with db() as connection:
            rows=connection.execute('SELECT id,name,archived,legacy_payload FROM logis_candidate.projects WHERE id=ANY(%s) ORDER BY name',(permissions.get('projects',[]),)).fetchall()
            return [{'id':x['id'],'name':x['name'],'archived':x['archived'],'kind':x['legacy_payload'].get('kind','project'),'updated':x['legacy_payload'].get('updated'),'running':False,'preview':''} for x in rows if q.casefold() in x['name'].casefold()]
    @app.get('/api/state')
    def legacy_state(id:str,permissions=Depends(scope)):
        allowed(id,permissions)
        with db() as connection:
            project=connection.execute('SELECT * FROM logis_candidate.projects WHERE id=%s',(id,)).fetchone()
            if not project:raise HTTPException(404,'Project not found')
            rows=connection.execute('SELECT m.id,m.role,m.content,m.legacy_index FROM logis_candidate.messages m JOIN logis_candidate.sources s ON s.id=m.source_id WHERE m.project_id=%s AND s.deleted_at IS NULL ORDER BY m.legacy_index',(id,)).fetchall()
            legacy=project['legacy_payload']
            return {'id':id,'name':project['name'],'kind':legacy.get('kind','project'),'brief':legacy.get('brief',''),'history':rows,'checkpoint':{},'context_policy':project['context_policy'],'job':None,'capabilities':{'conversation_read':True,'generation':False,'files':False},'migration_notice':'Imported conversation snapshot; live generation and file services are not connected.'}
    @app.get('/api/workspace')
    def legacy_workspace(view:str,permissions=Depends(scope)):
        supported={'tasks','decisions','cases','routines','pipelines','agents','skills','org','conference'}
        if view=='projects':return projects('',permissions)
        if view not in supported:raise HTTPException(501,'This workspace view has not been migrated')
        with db() as connection:
            rows=connection.execute('SELECT id,kind,project_id,version,status,payload FROM logis_candidate.objects WHERE project_id=ANY(%s) AND kind=%s ORDER BY updated_at DESC,id',(permissions.get('projects',[]),view)).fetchall()
            return [{**x['payload'],'id':x['id'],'kind':x['kind'],'project_id':x['project_id'],'version':x['version'],'status':x['status']} for x in rows]
    @app.get('/api/projects/{identifier}/messages')
    def messages(identifier:str,permissions=Depends(scope)):
        allowed(identifier,permissions)
        with db() as connection:return connection.execute('SELECT m.id,m.role,m.content,m.legacy_index FROM logis_candidate.messages m JOIN logis_candidate.sources s ON s.id=m.source_id WHERE m.project_id=%s AND s.deleted_at IS NULL ORDER BY m.legacy_index',(identifier,)).fetchall()
    @app.get('/api/projects/{identifier}/objects')
    def objects(identifier:str,permissions=Depends(scope)):
        allowed(identifier,permissions)
        with db() as connection:return connection.execute('SELECT id,kind,version,status,payload FROM logis_candidate.objects WHERE project_id=%s ORDER BY id',(identifier,)).fetchall()
    @app.get('/api/sources/{identifier}')
    def source(identifier:str,permissions=Depends(scope)):
        with db() as connection:
            row=connection.execute('SELECT id,project_id,kind,revision,checksum,payload FROM logis_candidate.sources WHERE id=%s AND deleted_at IS NULL',(identifier,)).fetchone()
            if not row:raise HTTPException(404,'Source not found')
            allowed(row['project_id'],permissions)
            return row
    @app.get('/api/objects/{identifier}/evidence')
    def evidence(identifier:str,permissions=Depends(scope)):
        with db() as connection:
            obj=connection.execute('SELECT project_id FROM logis_candidate.objects WHERE id=%s',(identifier,)).fetchone()
            if not obj:raise HTTPException(404,'Object not found')
            allowed(obj['project_id'],permissions)
            return connection.execute('SELECT e.source_id,e.source_revision,e.quote,e.active FROM logis_candidate.evidence e JOIN logis_candidate.sources s ON s.id=e.source_id WHERE e.object_id=%s AND s.project_id=ANY(%s) AND s.deleted_at IS NULL',(identifier,permissions.get('projects',[]))).fetchall()
    @app.post('/api/projects/{project}/objects')
    def create_record(project:str,body:RecordCreate,idempotency_key:str=Header(min_length=8,max_length=200),permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        if bool(body.source_id)!=bool(body.quote):raise HTTPException(422,'Provide both source and quote')
        fingerprint=hashlib.sha256(json.dumps({'operation':'create','project':project,'body':body.model_dump()},sort_keys=True).encode()).hexdigest()
        receipt_key=project+':'+idempotency_key
        with db(False) as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            prior=connection.execute('SELECT e.event_id,e.object_id,e.payload FROM logis_candidate.operation_receipts r JOIN logis_candidate.events e ON e.event_id=r.event_id WHERE r.idempotency_key=%s',(receipt_key,)).fetchone()
            if prior:
                if prior['payload'].get('request_hash')!=fingerprint:raise HTTPException(409,'Idempotency key already used')
                return {'id':prior['object_id'],'event_id':prior['event_id'],'version':1,'replayed':True}
            if not connection.execute('SELECT id FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone():raise HTTPException(404,'Project not found')
            source=None
            if body.source_id:
                source=connection.execute('SELECT revision,payload FROM logis_candidate.sources WHERE id=%s AND project_id=%s AND deleted_at IS NULL',(body.source_id,project)).fetchone()
                if not source:raise HTTPException(404,'Source not found')
                if body.quote not in source['payload'].get('content',''):raise HTTPException(422,'Quote does not match source')
            identifier=uuid.uuid4().hex[:16];event=uuid.uuid4().hex
            connection.execute('INSERT INTO logis_candidate.objects(id,kind,project_id,status,payload) VALUES(%s,%s,%s,%s,%s)',(identifier,body.kind,project,body.status,Jsonb({'title':body.title,'detail':body.detail})))
            if source:connection.execute('INSERT INTO logis_candidate.evidence VALUES(%s,%s,%s,%s,true)',(identifier,body.source_id,source['revision'],body.quote))
            connection.execute('INSERT INTO logis_candidate.events(event_id,event_type,object_id,actor_id,correlation_id,permissions_scope,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)',(event,body.kind+'.created',identifier,permissions.get('actor','local-user'),receipt_key,project,Jsonb({'version':1,'request_hash':fingerprint})))
            connection.execute('INSERT INTO logis_candidate.outbox(event_id) VALUES(%s)',(event,))
            connection.execute('INSERT INTO logis_candidate.operation_receipts VALUES(%s,%s)',(receipt_key,event))
            return {'id':identifier,'event_id':event,'version':1,'replayed':False}
    @app.patch('/api/projects/{project}/objects/{identifier}')
    def update(project:str,identifier:str,body:RecordUpdate,idempotency_key:str=Header(min_length=8,max_length=200),permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        fingerprint=hashlib.sha256(json.dumps({'project':project,'id':identifier,'body':body.model_dump()},sort_keys=True).encode()).hexdigest()
        receipt_key=project+':'+idempotency_key
        with db(False) as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            receipt=connection.execute('SELECT e.event_id,e.payload FROM logis_candidate.operation_receipts r JOIN logis_candidate.events e ON e.event_id=r.event_id WHERE r.idempotency_key=%s',(receipt_key,)).fetchone()
            if receipt:
                if receipt['payload'].get('request_hash')!=fingerprint:raise HTTPException(409,'Idempotency key already used for another request')
                return {'event_id':receipt['event_id'],'version':receipt['payload']['version'],'replayed':True}
            old=connection.execute('SELECT version,payload,kind FROM logis_candidate.objects WHERE id=%s AND project_id=%s FOR UPDATE',(identifier,project)).fetchone()
            if not old:raise HTTPException(404,'Object not found')
            if old['version']!=body.expected_version:raise HTTPException(409,'Record changed; reload before editing')
            version=old['version']+1;payload={**old['payload'],'title':body.title,'detail':body.detail,'status':body.status}
            connection.execute('UPDATE logis_candidate.objects SET version=%s,status=%s,payload=%s,updated_at=now() WHERE id=%s',(version,body.status,Jsonb(payload),identifier))
            event=uuid.uuid4().hex
            connection.execute('INSERT INTO logis_candidate.events(event_id,event_type,object_id,actor_id,correlation_id,permissions_scope,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)',(event,old['kind']+'.updated',identifier,permissions.get('actor','local-user'),receipt_key,project,Jsonb({'version':version,'request_hash':fingerprint})))
            connection.execute('INSERT INTO logis_candidate.outbox(event_id) VALUES(%s)',(event,))
            connection.execute('INSERT INTO logis_candidate.operation_receipts VALUES(%s,%s)',(receipt_key,event))
            return {'event_id':event,'version':version,'replayed':False}
    @app.get('/api/events')
    def events(after:int=Query(default=0,ge=0),limit:int=Query(default=100,ge=1,le=200),project:str|None=None,permissions=Depends(scope)):
        scopes=permissions.get('projects',[])
        if project is not None:allowed(project,permissions);scopes=[project]
        with db() as connection:
            rows=connection.execute('SELECT sequence,event_id,project_id,object_id,event_type,record_version,created_at FROM logis_candidate.activity_projection WHERE project_id=ANY(%s) AND sequence>%s ORDER BY sequence LIMIT %s',(scopes,after,limit+1)).fetchall()
        more=len(rows)>limit;rows=rows[:limit]
        return {'events':rows,'next_cursor':rows[-1]['sequence'] if rows else after,'has_more':more}
    return app
