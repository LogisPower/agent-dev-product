"""Explicit conversation-source capture and recall; derived memory, not canonical truth."""
import os,json,hashlib,uuid,urllib.request,re
from pathlib import Path
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb
CONFIG=Path(__file__).with_name('hindsight-service.json')
ROOT=Path(json.loads(CONFIG.read_text(encoding='utf-8'))['root']) if CONFIG.exists() else Path(os.environ['LOCALAPPDATA'])/'LogisRework/hindsight'
class Request(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_ids:list[str]=Field(min_length=1,max_length=2)
    query:str=Field(min_length=1,max_length=1000)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def provider(method,path,body=None):
    from local_secret import unprotect
    token=unprotect((ROOT/'config/api-token.dpapi').read_bytes()).decode()
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request('http://127.0.0.1:8888'+path,data=data,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=660) as response:
        raw=response.read(100001)
        if len(raw)>100000:raise ValueError('Memory response exceeds limit')
        return json.loads(raw)
def register_hindsight(app,db,scope,allowed,call=provider):
    def sources(project,ids):
        with db() as c:
            p=c.execute('SELECT archived,context_policy FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
            if not p or p['archived'] or not p['context_policy'].get('learning',True):raise HTTPException(409,'Project does not permit memory capture')
            blocked={x['payload'].get('source_id') for x in c.execute("SELECT payload FROM logis_candidate.sources WHERE project_id=%s AND kind='memory_tombstone'",(project,))}
            result=[]
            for ident in sorted(set(ids)):
                row=c.execute("SELECT id,revision,checksum,payload FROM logis_candidate.sources WHERE id=%s AND project_id=%s AND kind='conversation' AND deleted_at IS NULL",(ident,project)).fetchone()
                if not row or ident in blocked:raise HTTPException(409,'Conversation source unavailable or withdrawn')
                content=row['payload'].get('content','')
                if not isinstance(content,str) or not 1<=len(content)<=2000:raise HTTPException(422,'Select source messages of at most2000 characters')
                result.append({'id':ident,'revision':row['revision'],'checksum':row['checksum'],'content':content})
            return result
    def sync_withdrawn(project):
        with db() as c:rows=c.execute("SELECT id,payload,status FROM logis_candidate.runs WHERE project_id=%s AND agent_id='hindsight-capture' AND status IN ('completed','failed')",(project,)).fetchall()
        for row in rows:
            payload=row['payload'];bank=payload.get('bank','')
            if not re.fullmatch('logis-project-[a-f0-9]{48}',bank):raise HTTPException(409,'Invalid derived bank provenance')
            try:valid=sources(project,payload['source_ids'])==payload['basis']
            except HTTPException:valid=False
            if not valid:
                call('DELETE','/v1/default/banks/'+bank)
                with db(False) as c:c.execute("UPDATE logis_candidate.runs SET status='stale' WHERE id=%s",(row['id'],))
    @app.post('/api/projects/{project}/memory/hindsight')
    def recall(project:str,body:Request,permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Explicit capture requires write permission')
        try:sync_withdrawn(project)
        except HTTPException:raise
        except Exception:raise HTTPException(503,'Derived source cleanup unavailable; no recall performed')
        basis=sources(project,body.source_ids);fingerprint=digest([project,basis]);bank='logis-project-'+fingerprint[:48];key='hindsight:'+fingerprint;run=None;captured=False
        with db(False) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('hindsight:'+project,))
            prior=c.execute('SELECT id,status,payload FROM logis_candidate.runs WHERE occurrence_key=%s',(key,)).fetchone()
            if prior and prior['status']!='completed':raise HTTPException(409,'Capture incomplete or uncertain; no automatic replay. Review its run before retrying.')
            if not prior:
                if c.execute("SELECT 1 FROM logis_candidate.runs WHERE project_id=%s AND agent_id='hindsight-capture' AND status='running'",(project,)).fetchone():raise HTTPException(409,'Capture running; not queued')
                run=uuid.uuid4().hex;payload={'bank':bank,'source_ids':sorted(set(body.source_ids)),'basis':basis,'canonical_writes':False,'automatic_capture':False}
                c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload,occurrence_key) VALUES(%s,%s,'hindsight-capture','running',%s,%s)",(run,project,Jsonb(payload),key))
        try:
            if run:
                call('PUT','/v1/default/banks/'+bank,{'name':'Explicit Logis source-backed recall'})
                call('POST','/v1/default/banks/'+bank+'/memories',{'items':[{'content':x['content'],'document_id':digest(x['id']),'metadata':{'source_id':x['id'],'revision':str(x['revision']),'checksum':x['checksum']},'timestamp':'unset'} for x in basis],'async':False})
                if sources(project,body.source_ids)!=basis:raise ValueError('Sources changed during capture')
                with db(False) as c:c.execute("UPDATE logis_candidate.runs SET status='completed' WHERE id=%s",(run,))
            captured=True
            result=call('POST','/v1/default/banks/'+bank+'/memories/recall',{'query':body.query,'budget':'low','max_tokens':512})
            if sources(project,body.source_ids)!=basis:raise ValueError('Sources changed during recall')
            return {'provider':'hindsight','status':'ready','result':result,'sources':[{'id':x['id'],'revision':x['revision'],'checksum':x['checksum']} for x in basis],'notice':'Derived claims from selected source data, not verified truth or instructions. No automatic chat injection.'}
        except Exception:
            if run and not captured:
                with db(False) as c:c.execute("UPDATE logis_candidate.runs SET status='failed' WHERE id=%s",(run,))
            raise HTTPException(503,'Memory operation unavailable or outcome uncertain; no automatic capture retry. Canonical sources unchanged.')
