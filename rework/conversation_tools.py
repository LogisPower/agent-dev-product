"""A single explicit conversation tool, never a general autonomous executor."""
import re,uuid,hashlib,json
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from candidate_documents import DocumentRequest
class BriefContext(BaseModel):
    model_config=ConfigDict(extra='forbid')
    file_ids:list[str]=Field(min_length=1,max_length=3)
    memory_record_id:str|None=None
    approve_local_brief:bool=False

def intent(text,context):
    if context:return 'brief' if context.approve_local_brief else 'clarify'
    if re.search(r'\b(?:create|save|make|prepare)\b.{0,40}\b(?:evidence|source-backed|sourced)\s+brief\b',text,re.I):return 'clarify'
    return None

def route(app,db,save_message,project,body,key,permissions):
    mode=intent(body.content,body.brief_context)
    if not mode:return None
    if mode=='brief' and len(body.content)>1000:raise HTTPException(422,'Brief request exceeds 1000 characters')
    fingerprint=hashlib.sha256(body.model_dump_json().encode()).hexdigest();receipt_key='chat:'+project+':'+key
    with db(False) as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
        prior=c.execute('SELECT id,status,payload FROM logis_candidate.runs WHERE occurrence_key=%s',(receipt_key,)).fetchone()
        if prior:
            if prior['payload'].get('request_hash')!=fingerprint:raise HTTPException(409,'Request identity changed')
            return {**prior,'replayed':True}
        if not c.execute('SELECT id FROM logis_candidate.projects WHERE id=%s AND NOT archived',(project,)).fetchone():raise HTTPException(404,'Active project required')
        run=uuid.uuid4().hex;user=save_message(c,project,'user',body.content)
        payload={'mode':'explicit_evidence_brief','request_hash':fingerprint,'user_message_id':user,'notice':'Dispatch outcome not yet confirmed; never automatically retry.'}
        c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload,occurrence_key) VALUES(%s,%s,'local-chat','dispatching',%s,%s)",(run,project,Jsonb(payload),receipt_key))
    task=None
    try:
        if mode=='clarify':message='To create a source-backed brief, open Use sources, select project files and optionally one confirmed memory, then explicitly approve the local brief. Nothing has executed.'
        elif mode=='status':
            with db() as c:task=c.execute("SELECT t.id,t.status FROM logis_candidate.runs t JOIN logis_candidate.runs chat ON chat.payload->>'task_id'=t.id JOIN logis_candidate.messages m ON m.id=chat.payload->>'user_message_id' WHERE t.project_id=%s AND t.agent_id='document-answer' ORDER BY m.legacy_index DESC LIMIT 1",(project,)).fetchone()
            message='No evidence task found in this project.' if not task else 'Recorded evidence task status: '+task['status']+'. Open the result for current source validity; completion alone does not verify every claim.'
        else:
            context=body.brief_context
            task=app.state.document_submit(project,DocumentRequest(query=body.content[:1000],file_ids=context.file_ids,memory_record_id=context.memory_record_id,confirmed_memory_use=bool(context.memory_record_id),local_documents_confirmed=True,save_evidence_brief=True),'conversation-'+run,permissions)
            message=('Evidence task accepted. It runs independently of this chat. Open its result to check current source provenance and verification.' if task['status']=='running' else 'Evidence task did not start or is unavailable. Inspect its status; no automatic retry.')
        with db(False) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(project,))
            current=c.execute('SELECT status FROM logis_candidate.runs WHERE id=%s FOR UPDATE',(run,)).fetchone()
            if current['status']!='dispatching':return {'id':run,'status':current['status'],'payload':{'notice':'Dispatch interrupted; inspect task state before retry'},'replayed':False}
            assistant=save_message(c,project,'assistant',message)
            payload={**payload,'assistant_message_id':assistant,'notice':message,'task_id':task['id'] if task else None,'task_kind':'document-answer' if task else None,'clarification_required':mode=='clarify','task_completed':False}
            c.execute("UPDATE logis_candidate.runs SET status='completed',payload=%s WHERE id=%s",(Jsonb(payload),run))
        return {'id':run,'status':'completed','payload':payload,'replayed':False}
    except Exception as error:
        # A dispatch exception can follow a side effect: never silently resubmit.
        with db(False) as c:c.execute("UPDATE logis_candidate.runs SET status='failed',payload=payload || %s WHERE id=%s AND status='dispatching'",(Jsonb({'error_type':type(error).__name__,'notice':'Tool dispatch failed or its outcome is uncertain. Inspect task Activity; automatic retry is disabled.'}),run))
        return {'id':run,'status':'failed','payload':{'mode':'explicit_evidence_brief','notice':'Tool dispatch unavailable. No automatic retry; inspect Activity.'},'replayed':False}
