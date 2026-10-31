"""Opt-in document answers through the existing evidence worker and canonical runs."""
import uuid,re,os
from task_memory import combined_loader,memory_row,recall_checked
from pathlib import Path
from evidence_brief import save as save_brief,verify as verify_brief
BRIEF_ROOT=Path(os.environ["LOCALAPPDATA"])/"LogisRework/data/evidence-briefs"
from fastapi import Depends,Header,HTTPException
from pydantic import BaseModel,Field,ConfigDict,field_validator
from psycopg.types.json import Jsonb
from document_rag import snapshot,digest,answer_documents,selected_file_loader,nomic

class DocumentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=1000)
    file_ids:list[str]=Field(min_length=1,max_length=4)
    local_documents_confirmed:bool=False
    save_evidence_brief:bool=False
    memory_record_id:str|None=Field(default=None,pattern="^[a-zA-Z0-9_-]{1,200}$")
    confirmed_memory_use:bool=False
    @field_validator('file_ids')
    @classmethod
    def bounded_ids(cls,value):
        if any(not re.fullmatch('[a-f0-9]{64}',x) for x in value):raise ValueError('Invalid file identifier')
        return value

def register_documents(app,db,scope,allowed,dispatch,loader=None,embed=None,answerer=None):
    loader=loader or selected_file_loader(db)
    def visible(project,row):
        payload=row['payload']
        current_loader=combined_loader(app,loader,payload.get('memory_record_id'))
        try:
            if digest(snapshot(current_loader,project,payload['file_ids']))!=payload['source_fingerprint']:raise ValueError('Sources changed')
            receipt=payload.get("result",{}).get("artifact")
            if receipt:verify_brief(BRIEF_ROOT,row["id"],receipt,project,payload["file_ids"],current_loader,payload["source_fingerprint"])
        except Exception:
            return {'id':row['id'],'status':'unavailable','recorded_status':row['status'],'payload':{'notice':'Selected sources changed, were removed, or are no longer allowed. Saved answer withheld; select current files for a new request.'}}
        return row
    @app.get('/api/projects/{project}/documents/runs/{run}')
    def read(project:str,run:str,permissions=Depends(scope)):
        allowed(project,permissions)
        with db() as c:row=c.execute("SELECT id,status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s AND agent_id='document-answer'",(run,project)).fetchone()
        if not row:raise HTTPException(404,'Document run not found')
        return visible(project,row)
    @app.post('/api/projects/{project}/documents/answer')
    def start(project:str,body:DocumentRequest,idempotency_key:str=Header(min_length=8,max_length=200),permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        if not body.local_documents_confirmed or not body.query.strip():raise HTTPException(422,'Confirm use of these selected documents by local Nomic and Bonsai')
        if body.memory_record_id and (not body.confirmed_memory_use or len(body.file_ids)>3):raise HTTPException(422,'Confirm one memory and select at most three files')
        current_loader=combined_loader(app,loader,body.memory_record_id)
        ids=sorted(body.file_ids+(['memory:'+body.memory_record_id] if body.memory_record_id else []));query=body.query.strip();request_hash=digest([query,ids,body.save_evidence_brief]);key='documents:'+project+':'+idempotency_key
        with db(False) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            prior=c.execute('SELECT id,status,payload FROM logis_candidate.runs WHERE occurrence_key=%s',(key,)).fetchone()
            if prior:
                if prior['payload'].get('request_hash')!=request_hash:raise HTTPException(409,'Request identity belongs to different input')
                return {**visible(project,prior),'replayed':True}
            if c.execute("SELECT id FROM logis_candidate.runs WHERE project_id=%s AND status='running'",(project,)).fetchone():raise HTTPException(409,'Project work active; nothing queued')
            try:before=snapshot(current_loader,project,ids)
            except Exception:raise HTTPException(409,'Selected files unavailable, empty, oversized, changed or excluded') from None
            run=uuid.uuid4().hex;fingerprint=digest(before)
            payload={'memory_record_id':body.memory_record_id,'query':query,'file_ids':ids,'request_hash':request_hash,'source_fingerprint':fingerprint,'save_evidence_brief':body.save_evidence_brief,'mode':'explicit_local_documents','notice':'Only selected files are used locally. No web query, automatic memory capture or legacy index change.'}
            c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload,occurrence_key) VALUES(%s,%s,'document-answer','running',%s,%s)",(run,project,Jsonb(payload),key))
        def execute():
            from candidate_chat import bounded_chat
            def local_embed(texts):
                from inference_gate import inference_slot
                from research_graph import BUILDER
                with inference_slot(BUILDER/'runtime/inference.lock',timeout=0):return nomic(texts)
            memory=None
            if body.memory_record_id:
                expected=next(row for row in before if row["id"].startswith("memory:"))
                memory=recall_checked(app,project,body.memory_record_id,query,permissions,expected)
            result=answer_documents(project,ids,query,current_loader,embed or local_embed,answerer or bounded_chat,expected_fingerprint=fingerprint)
            if memory:result["memory"]=memory
            if body.save_evidence_brief:result["artifact"]=save_brief(BRIEF_ROOT,run,project,ids,current_loader,fingerprint,result)
            return result
        return dispatch(project,run,payload,execute)

    app.state.document_submit=start
