"""Scoped, reversible project metadata. Never moves files or expands access."""
import hashlib,json,uuid
from fastapi import Depends,Header,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb

class ContextPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sources:list[str]=Field(default_factory=list,max_length=40)
    learning:bool=True

class ProjectUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(ge=1)
    name:str|None=Field(default=None,min_length=1,max_length=80)
    brief:str|None=Field(default=None,max_length=12000)
    archived:bool|None=None
    trash:bool|None=None
    context_policy:ContextPolicy|None=None

def register(app,db,scope,allowed):
    def snapshot(row):
        meta=row['legacy_payload']
        return {'id':row['id'],'name':row['name'],'archived':row['archived'],
                'trashed':bool(meta.get('_ui_trashed')), 'brief':meta.get('brief',''),
                'version':meta.get('_ui_version',1),'context_policy':row['context_policy']}

    @app.get('/api/projects/{project}/settings')
    def settings(project:str,permissions=Depends(scope)):
        allowed(project,permissions)
        with db() as c:
            row=c.execute('SELECT * FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
            if not row:raise HTTPException(404,'Project not found')
            return snapshot(row)

    @app.patch('/api/projects/{project}/settings')
    def update(project:str,body:ProjectUpdate,idempotency_key:str=Header(min_length=8,max_length=200),permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        changes=body.model_dump(exclude_unset=True);changes.pop('expected_version')
        if not changes or any(v is None for v in changes.values()):raise HTTPException(422,'Provide explicit metadata changes')
        if body.name is not None and not body.name.strip():raise HTTPException(422,'Project name is empty')
        if body.trash is not None and body.archived is not None:raise HTTPException(422,'Trash and archive are separate actions')
        fingerprint=hashlib.sha256(json.dumps(body.model_dump(),sort_keys=True).encode()).hexdigest()
        key='project-settings:'+project+':'+idempotency_key
        with db(False) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            prior=c.execute('SELECT e.payload FROM logis_candidate.operation_receipts r JOIN logis_candidate.events e ON e.event_id=r.event_id WHERE r.idempotency_key=%s',(key,)).fetchone()
            if prior:
                if prior['payload']['request_hash']!=fingerprint:raise HTTPException(409,'Idempotency key already used')
                return {**prior['payload']['result'],'replayed':True}
            row=c.execute('SELECT * FROM logis_candidate.projects WHERE id=%s FOR UPDATE',(project,)).fetchone()
            if not row:raise HTTPException(404,'Project not found')
            meta=dict(row['legacy_payload'])
            if meta.get('_ui_version',1)!=body.expected_version:raise HTTPException(409,'Project changed; reload before editing. Draft not applied.')
            if meta.get('_ui_trashed') and set(changes)!={'trash'}:raise HTTPException(409,'Restore this project before editing')
            if body.archived is not None or body.trash is not None:
                if c.execute("SELECT 1 FROM logis_candidate.runs WHERE project_id=%s AND status='running' LIMIT 1",(project,)).fetchone():raise HTTPException(409,'Project has active or queued work; cancel or finish it before archiving or restoring')
                foundation=getattr(app.state,'foundation',None)
                if foundation is not None and foundation.ledger.has_active(project):raise HTTPException(409,'File work is active; finish it before changing project availability')
            if body.context_policy is not None:
                ids=body.context_policy.sources
                if len(set(ids))!=len(ids) or project in ids:raise HTTPException(422,'Context sources must be distinct other projects')
                for identifier in ids:allowed(identifier,permissions)
                if ids and c.execute('SELECT count(*) AS n FROM logis_candidate.projects WHERE id=ANY(%s) AND NOT archived',(ids,)).fetchone()['n']!=len(ids):raise HTTPException(409,'A context source is unavailable')
                row['context_policy']={**row['context_policy'],**body.context_policy.model_dump()}
            if body.name is not None:row['name']=body.name.strip()
            if body.brief is not None:meta['brief']=body.brief
            if body.archived is not None:row['archived']=body.archived
            if body.trash is True:
                if not meta.get('_ui_trashed'):meta['_ui_prior_archived']=row['archived']
                meta['_ui_trashed']=True;row['archived']=True
            elif body.trash is False:
                if not meta.get('_ui_trashed'):raise HTTPException(409,'Project is not in Trash')
                row['archived']=bool(meta.pop('_ui_prior_archived',False));meta['_ui_trashed']=False
            meta['_ui_version']=body.expected_version+1;row['legacy_payload']=meta
            c.execute('UPDATE logis_candidate.projects SET name=%s,archived=%s,context_policy=%s,legacy_payload=%s WHERE id=%s',(row['name'],row['archived'],Jsonb(row['context_policy']),Jsonb(meta),project))
            result=snapshot(row);event=uuid.uuid4().hex
            c.execute("INSERT INTO logis_candidate.events(event_id,event_type,object_id,actor_id,correlation_id,permissions_scope,payload) VALUES(%s,'project.metadata_updated',%s,%s,%s,%s,%s)",(event,project,permissions.get('actor','local-user'),key,project,Jsonb({'version':meta['_ui_version'],'request_hash':fingerprint,'result':result})))
            c.execute('INSERT INTO logis_candidate.outbox(event_id) VALUES(%s)',(event,))
            c.execute('INSERT INTO logis_candidate.operation_receipts VALUES(%s,%s)',(key,event))
            return result

    @app.get('/api/projects/{project}/conversation')
    def conversation(project:str,after:int=Query(default=-1,ge=-1),limit:int=Query(default=50,ge=1,le=100),permissions=Depends(scope)):
        allowed(project,permissions)
        with db() as c:
            rows=c.execute('SELECT m.id,m.source_id,m.role,m.content,m.legacy_index FROM logis_candidate.messages m JOIN logis_candidate.sources s ON s.id=m.source_id WHERE m.project_id=%s AND s.deleted_at IS NULL AND m.legacy_index>%s ORDER BY m.legacy_index LIMIT %s',(project,after,limit+1)).fetchall()
            more=len(rows)>limit;rows=rows[:limit]
            return {'messages':rows,'has_more':more,'next_cursor':rows[-1]['legacy_index'] if rows else after}
