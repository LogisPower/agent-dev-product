"""Explicit, authenticated public research with canonical run state.

No chat history, files or memories are sent to search. No autonomous follow-up.
Graph checkpoints are derived execution records; PostgreSQL owns run truth.
"""
import hashlib,json,threading,uuid
from pathlib import Path
from fastapi import Depends,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb

class ResearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=500)
    public_query_confirmed:bool=False

def register_research(app,db,scope,allowed,checkpoint_dir,runner=None,document_loader=None,document_embed=None,document_answerer=None):
    capacity=threading.BoundedSemaphore(1)
    from harness_queue import scheduler
    work_queue=scheduler(app)
    app.state.research_worker={'status':'idle'}
    def execute(query,run):
        from research_graph import research
        from candidate_chat import bounded_chat
        directory=Path(checkpoint_dir)
        directory.mkdir(parents=True,exist_ok=True)
        return research(query,directory/'research.sqlite',run,answerer=bounded_chat)
    execute=runner or execute
    def intent_research(action,run,answerer):
        from research_graph import research
        directory=Path(checkpoint_dir);directory.mkdir(parents=True,exist_ok=True)
        value=(runner(action.query,run) if runner else research(action.query,directory/'research.sqlite',run+'-'+action.tool,answerer=answerer,direct_url=action.query if action.tool=='web_read' else None))
        sources=value.get('sources',[])
        answer=value.get('answer','') if value.get('status')=='answered' else value.get('notice','Public evidence unavailable; no answer fabricated.')
        if sources:answer+='\n\n'+ '\n'.join('['+x['id']+'] '+x['url'] for x in sources)
        return {'diagnostics':value.get('diagnostics',[]),'status':value.get('status','unavailable'),'answer':answer,'sources':[{'id':x['id'],'url':x['url'],'sha256':x['sha256'],'fetched_at':x['fetched_at']} for x in sources],'tool':action.tool,'claim_verification':'Citations identify read sources; not independent proof of every claim'}
    app.state.intent_research=intent_research


    @app.get('/api/projects/{project}/research/runs/{run}')
    def inspect(project:str,run:str,permissions=Depends(scope)):
        allowed(project,permissions)
        with db() as c:
            row=c.execute("SELECT id,status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s AND agent_id='public-research'",(run,project)).fetchone()
        if not row:raise HTTPException(404,'Research run not found')
        return row

    @app.post('/api/projects/{project}/research')
    def start(project:str,body:ResearchRequest,idempotency_key:str=Header(min_length=8,max_length=200),permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        query=body.query.strip()
        if not query or not body.public_query_confirmed:raise HTTPException(422,'Confirm that this exact query may be sent to public search. Do not include private data.')
        fingerprint=hashlib.sha256(query.encode()).hexdigest()
        key='research:'+project+':'+idempotency_key
        with db(False) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            prior=c.execute('SELECT id,status,payload FROM logis_candidate.runs WHERE occurrence_key=%s',(key,)).fetchone()
            if prior:
                if prior['payload'].get('request_hash')!=fingerprint:raise HTTPException(409,'Request identity belongs to another query')
                return {**prior,'replayed':True}
            if not c.execute('SELECT id FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone():raise HTTPException(404,'Project not found')
            if c.execute("SELECT id FROM logis_candidate.runs WHERE project_id=%s AND status='running'",(project,)).fetchone():raise HTTPException(409,'Project work is active; research was not queued')
            run=uuid.uuid4().hex
            payload={'request_hash':fingerprint,'public_query':query,'mode':'explicit_public_research','notice':'Only this confirmed query is sent to public search; no history or private sources are attached.'}
            c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload,occurrence_key) VALUES(%s,%s,'public-research','running',%s,%s)",(run,project,Jsonb(payload),key))
        return dispatch(project,run,payload,lambda:execute(query,run))

    def dispatch(project,run,payload,job):
        def terminal(status,extra):
            with db(False) as c:
                c.execute("UPDATE logis_candidate.runs SET status=%s,payload=payload || %s WHERE id=%s AND status='running'",(status,Jsonb({**payload,**extra,'harness_phase':status,'generation_id':run}),run))
        if not capacity.acquire(blocking=False):
            terminal('failed',{'notice':'Evidence worker busy. No retrieval started; no automatic retry.'})
            return {'id':run,'status':'failed','replayed':False}
        def work(waited):
            try:
                with db(False) as c:
                    current=c.execute("SELECT status FROM logis_candidate.runs WHERE id=%s",(run,)).fetchone()
                    if not current or current['status']!='running':return
                    if waited>300:
                        c.execute("UPDATE logis_candidate.runs SET status='failed',payload=payload || %s WHERE id=%s",(Jsonb({'notice':'Evidence queue wait exceeded five minutes; no job executed.'}),run));return
                    c.execute("UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s",(Jsonb({'harness_phase':'running','queue_seconds':round(waited,3),'generation_id':run}),run))
                result=job()
                # Keep source evidence inspectable; never promote synthesis to memory/fact.
                terminal('completed' if result.get('status') in ('answered','sources_only') else 'failed',{'result':result,'claim_verification':'Source citations are recorded; individual claims are not independently guaranteed.'})
                app.state.research_worker={'status':'idle'}
            except Exception as error:
                try:
                    terminal('failed',{'error_type':type(error).__name__,'notice':'Research failed. No automatic replay or remote model fallback.'})
                    app.state.research_worker={'status':'idle'}
                except Exception as save_error:
                    app.state.research_worker={'status':'attention','error_type':type(save_error).__name__,'notice':'Canonical outcome could not be saved. Inspect before retry; never replay automatically.'}
            finally:capacity.release()
        app.state.research_worker={'status':'running'}
        try:
            with db(False) as c:c.execute("UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s AND status='running'",(Jsonb({'harness_phase':'queued','generation_id':run}),run))
            work_queue.submit(run,work,foreground=False)
        except Exception:
            capacity.release()
            app.state.research_worker={'status':'attention','error_type':'WorkerLaunchError'}
            terminal('failed',{'error_type':'WorkerLaunchError','notice':'Research worker did not start. No search executed.'})
            return {'id':run,'status':'failed','replayed':False}
        return {'id':run,'status':'running','payload':payload,'replayed':False}

    from candidate_documents import register_documents
    register_documents(app,db,scope,allowed,dispatch,document_loader,document_embed,document_answerer)
