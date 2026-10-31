"""Optional authenticated local-work routes; registration never starts a worker."""
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path:str=Field(min_length=1,max_length=180)
    expected_sha256:str=Field(pattern='^[a-f0-9]{64}$')
    old:str=Field(min_length=1,max_length=32768)
    new:str=Field(max_length=32768)


class Dependency(BaseModel):
    model_config=ConfigDict(extra='forbid')
    task:str=Field(pattern='^[a-f0-9]{32}$')
    path:str=Field(min_length=1,max_length=180)


class Submission(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    edits:list[Edit]=Field(min_length=1,max_length=4)
    dependencies:list[Dependency]=Field(default_factory=list,max_length=8)


class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    task:str=Field(pattern='^[a-f0-9]{32}$')
    version:int=Field(ge=1,strict=True)


class PlanStep(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(pattern='^[a-z][a-z0-9_-]{0,39}$')
    edit:Edit
    after:list[str]=Field(default_factory=list,max_length=8)


class PlanSubmission(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    title:str=Field(min_length=1,max_length=120)
    steps:list[PlanStep]=Field(min_length=1,max_length=8)


def public(task):
    result={k:v for k,v in task.items() if k in ('id','kind','status','version','attempts','max_attempts','dependencies','checkpoint','result','artifacts','created','updated')}
    result['targets']=task['payload'].get('targets',[])
    if task['kind']=='local_plan':result['planning']={'goal':task['payload']['goal'],'paths':[item['path'] for item in task['payload']['files']],'discovery':task['payload'].get('_discovery')}
    if task['kind']=='local_discovery':result['discovery']={k:task['payload'][k] for k in ('query','directory')}
    if task['kind']=='local_verify':result['verification']={'paths':[item['path'] for item in task['payload']['files']]}
    if task['kind']=='local_author':result['authoring']={'goal':task['payload']['goal'],'path':task['payload']['path'],'context_paths':[item['path'] for item in task['payload']['files']]}
    plan=task['payload'].get('_plan')
    if plan:result['plan']={k:plan[k] for k in ('id','title','name','position','total','after')}
    return result


def register(app, loop, scope, allowed, resolve_identity, db):
    previous=loop.authorize
    def available(project):
        with db() as connection:
            row=connection.execute('SELECT archived FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
        return bool(row and not row['archived'])
    def authorize(task):
        identity=task['payload'].get('_principal')
        if not identity:return False
        current=resolve_identity(identity)
        return bool(current.get('write') and task['project'] in current.get('projects',[]) and available(task['project']) and previous(task))
    loop.authorize=authorize;loop.worker.authorize=authorize
    handler=loop.worker.handlers['local_exact_edit']
    def locked_handler(attempt,files,payload):
        # Cooperating canonical file effects/archive use this same project lock.
        # Do not block an approved local job indefinitely behind another writer.
        with db(False) as connection:
            locked=connection.execute('SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS locked',(attempt.task['project'],)).fetchone()['locked']
            if not locked:raise ValueError('Project has another active file effect; no local submission')
            attempt.check()
            if not authorize(attempt.task):raise PermissionError('Project access withdrawn')
            return handler(attempt,files,payload)
    loop.worker.handlers['local_exact_edit']=locked_handler
    def check(project,permissions,write=False):
        allowed(project,permissions)
        if write and not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        if not available(project):raise HTTPException(404,'Project unavailable')
        loop.files(project)
    def guarded(fn):
        try:return fn()
        except KeyError as error:raise HTTPException(404,'Local task not found') from error
        except PermissionError as error:raise HTTPException(403,'Local work access unavailable') from error
        except (ValueError,OSError) as error:raise HTTPException(409,str(error)) from error

    @app.get('/api/projects/{project}/local-work')
    def query(project:str, action:str='status', path:str=Query(default='',max_length=180), after:int=Query(default=0,ge=0), task:str=Query(default='',max_length=32), permissions=Depends(scope)):
        def read():
            check(project,permissions)
            if action=='workflow':
                from local_workflow import workflow
                value=workflow(loop,project,task)
                value['proposal']=public(value['proposal']);value['tasks']=[public(item) for item in value['tasks']]
                return value
            if action=='context':
                from local_planning_context import planning_context
                return planning_context(loop,project,[path] if path else [])
            if action=='prepare':
                value=loop.files(project).read(path,limit=32768)
                if value['status']=='missing':return value
                if value['next_offset'] is not None:raise ValueError('File exceeds the local editor preview bound; prepare a bounded task separately')
                return value
            if action!='status':raise ValueError('Unknown local work query')
            page=loop.ledger.list(project,after)
            return {'tasks':[public(t) for t in page['tasks']],'next_cursor':page['next_cursor'],
                'has_more':page['has_more'],'worker':loop.worker.status,'worker_error':loop.worker.error_type,'planning_enabled':getattr(loop,'planner',None) is not None}
        return guarded(read)

    @app.post('/api/projects/{project}/local-work/submit')
    def submit(project:str,body:Submission,permissions=Depends(scope)):
        def write():
            check(project,permissions,True)
            identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            task=loop.submit(project,body.key,[e.model_dump() for e in body.edits],principal=identity,
                             dependencies=[d.model_dump() for d in body.dependencies])
            return public(task)
        return guarded(write)

    @app.post('/api/projects/{project}/local-work/plan')
    def plan(project:str,body:PlanSubmission,permissions=Depends(scope)):
        def write():
            check(project,permissions,True)
            identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            from local_work_plan import submit_plan
            result=submit_plan(loop,project,body.key,body.title,[step.model_dump() for step in body.steps],identity)
            result['tasks']=[public(task) for task in result['tasks']]
            return result
        return guarded(write)

    @app.post('/api/projects/{project}/local-work/{action}')
    def command(project:str,action:str,body:Decision,permissions=Depends(scope)):
        def write():
            check(project,permissions,True)
            task=loop.ledger.get(project,body.task)
            if task['kind']!='local_exact_edit':raise ValueError('Not a local edit task')
            if action=='approve':return public(loop.approve(project,body.task,body.version))
            if action=='reconcile':return public(loop.reconcile(project,body.task,body.version))
            if action=='cancel':return public(loop.ledger.cancel(project,body.task))
            raise ValueError('Unknown local work action')
        return guarded(write)
    setattr(app.state,'local_work',loop)
    from contextlib import contextmanager
    @contextmanager
    def admission(project):
        # Serialize proposal acceptance across both private ledgers and app processes.
        with db() as connection:
            acquired=connection.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired",('logis-proposal-admission:'+project,)).fetchone()['acquired']
            if not acquired:raise ValueError('Another proposal admission is active; retry this same request identity')
            yield
    from local_planner_api import register as register_planning
    register_planning(app,loop,scope,check,guarded,public,admission)
