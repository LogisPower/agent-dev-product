"""Explicit evidence-linked lesson candidates; never automatic memory or promotion."""
import hashlib,json,uuid
from fastapi import Depends,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb
class LessonRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    failed_run:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,200}$')
    proposed_rule:str=Field(min_length=10,max_length=1000)
    regression_case:str=Field(min_length=10,max_length=1000)
def register_lessons(app,db,scope,allowed):
    @app.post('/api/projects/{project}/harness/lesson-candidates')
    def propose(project:str,body:LessonRequest,idempotency_key:str=Header(min_length=8,max_length=200),permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        from intent_core import SECRET
        if SECRET.search(body.proposed_rule+' '+body.regression_case):raise HTTPException(422,'Sensitive content cannot be recorded as a lesson')
        fingerprint=hashlib.sha256(body.model_dump_json().encode()).hexdigest();key='lesson:'+project+':'+idempotency_key
        with db(False) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            prior=c.execute('SELECT id,status,payload FROM logis_candidate.runs WHERE occurrence_key=%s',(key,)).fetchone()
            if prior:
                if prior['payload']['request_hash']!=fingerprint:raise HTTPException(409,'Request identity changed')
                return {**prior,'replayed':True}
            source=c.execute('SELECT id,status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s',(body.failed_run,project)).fetchone()
            if not source or source['status'] not in ('failed','interrupted','canceled'):raise HTTPException(409,'Select a recorded failed/interrupted/canceled run in this project')
            digest=hashlib.sha256(json.dumps(source['payload'],sort_keys=True,default=str).encode()).hexdigest()
            payload={'request_hash':fingerprint,'source_run':source['id'],'source_status':source['status'],'source_payload_sha256':digest,'proposed_rule':body.proposed_rule,'regression_case':body.regression_case,'verification':'failure receipt linked; proposed rule and regression NOT verified','promotion':'disabled','automatic_capture':False,'authority_change_allowed':False}
            ident=uuid.uuid4().hex
            c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload,occurrence_key) VALUES(%s,%s,'harness-lesson','needs_review',%s,%s)",(ident,project,Jsonb(payload),key))
            return {'id':ident,'status':'needs_review','payload':payload,'replayed':False}
    @app.get('/api/projects/{project}/harness/lesson-candidates')
    def candidates(project:str,permissions=Depends(scope)):
        allowed(project,permissions)
        with db() as c:return c.execute("SELECT id,status,payload FROM logis_candidate.runs WHERE project_id=%s AND agent_id='harness-lesson' ORDER BY id LIMIT 50",(project,)).fetchall()
