"""Project-partitioned facade; exact approved-root grant, no inferred OS access."""
import os,json,hashlib
from pathlib import Path
from workspace_files import Workspace

APPROVED_ROOT=Path(r'C:\Users\LOGIS_USER\Documents\LogisWorkspaces')
GRANT=Path(r'C:\Users\LOGIS_USER\AppData\Local\LogisRework\config\workspace-grant.json')

def enabled():
    try:
        value=json.loads(GRANT.read_text(encoding='utf-8'))
        return value=={'schema_version':1,'root':str(APPROVED_ROOT),'operations':['create','read','edit','move'],'project_partitioned':True}
    except (OSError,ValueError):return False

def workspace(project,permissions):
    if project not in permissions.get('projects',[]):raise PermissionError('Project not authorized')
    if not enabled():raise PermissionError('Approved workspace grant is not installed; no directory accessed')
    name=hashlib.sha256(project.encode()).hexdigest()
    # Provision project folder and journal during controlled deployment/onboarding,
    # not by following arbitrary model-provided filesystem paths.
    return Workspace(APPROVED_ROOT/name)

def execute(db,project,action,permissions,run,admission_check=None,files_resolver=None):
    kind=action.tool.removeprefix('workspace_')
    files=files_resolver(project,permissions,kind not in ('read','list','search')) if files_resolver is not None else None
    w=files.workspace if files is not None else workspace(project,permissions)
    if kind in ('read','list','search'):
        from project_files import ProjectFiles
        files=files if files is not None else ProjectFiles(w.root)
        if kind=='read':return files.read(action.path,offset=action.offset,limit=12000,expected_sha256=action.expected_sha256 or None)
        if kind=='list':return files.listing(action.path,cursor=action.cursor or None,limit=50)
        return files.search(action.query,directory=action.path,content=True,cursor=action.cursor or None,limit=50)
    if not permissions.get('write'):raise PermissionError('Read-only session')
    from psycopg.types.json import Jsonb
    # Serialize cancel acknowledgment with effect; OS receipts survive uncertain DB commit.
    with db(False) as c:
        if files_resolver is not None:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            available=c.execute('SELECT archived FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
            if not available or available['archived']:raise PermissionError('Project unavailable')
            files=files_resolver(project,permissions,True);w=files.workspace
        state=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s FOR UPDATE',(run,project)).fetchone()
        if not state or state['status']!='running' or state['payload'].get('cancel_requested'):raise ValueError('Origin stopped; no workspace mutation')
        if admission_check is not None:
            from setup_admission import AdmissionDenied
            try:admission_check()
            except AdmissionDenied as denied:
                # Commit the final pre-write decision in the same locked run
                # transaction. This branch never enters the filesystem mutation.
                c.execute('UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s AND project_id=%s',(Jsonb({'setup_admission':denied.decision}),run,project))
                return {'status':'prewrite_denied','admission':denied.decision,'effect':'none'}
        path=files.relative(action.path) if files_resolver is not None else action.path
        destination=(files.relative(action.destination) if files_resolver is not None else action.destination) if kind=='move' else None
        result=w.mutate(kind,path,request_id=run,content=action.text if kind!='move' else None,
            expected_sha256=action.expected_sha256 or None,destination=destination)
        c.execute("UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s",(Jsonb({'settled_effect':{'tool':action.tool,'receipt':result}}),run))
    return result

def register_recovery(app,db,scope,allowed):
    from fastapi import Depends,HTTPException
    @app.get('/api/projects/{project}/workspace/effects/{run}')
    def inspect_effect(project:str,run:str,permissions=Depends(scope)):
        allowed(project,permissions)
        with db() as c:
            row=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s',(run,project)).fetchone()
        if not row:raise HTTPException(404,'Origin not found in this project')
        try:
            resolver=getattr(app.state,'project_files',None)
            selected=resolver(project,permissions,False).workspace if resolver is not None else workspace(project,permissions)
            disk=selected.inspect(run)
        except (OSError,ValueError,PermissionError) as e:raise HTTPException(409,'Workspace inspection unavailable: '+str(e)) from e
        settled=row['payload'].get('settled_effect')
        return {'run':run,'task_status':row['status'],'filesystem':disk,'database_effect_recorded':bool(settled),
          'cross_store_status':'filesystem_verified_database_missing' if disk['state']=='verified_effect_observed' and not settled else 'inspect_evidence',
          'mutations_performed':False,'replay_allowed':False}
