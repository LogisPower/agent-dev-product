"""Explicit source-backed Mnemosyne recall; no automatic chat injection or dual writer."""
import os,sys,json,hashlib,subprocess
from pathlib import Path
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
B=Path(__file__).resolve().parents[1]
if str(B) not in sys.path:sys.path.insert(0,str(B))
class RecallBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=1000)
    record_ids:list[str]=Field(min_length=1,max_length=32)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
def register_memory(app,db,scope,allowed):
    def projection(project,ids):
        with db() as c:
            p=c.execute('SELECT archived,context_policy FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
            if not p or p['archived'] or p['context_policy'].get('learning',True) is False:raise HTTPException(409,'Project does not permit memory recall')
            blocked={x['payload'].get('source_id') for x in c.execute("SELECT payload FROM logis_candidate.sources WHERE project_id=%s AND kind='memory_tombstone'",(project,))}
            rows=[];mapping={}
            for ident in sorted(set(ids)):
                record=c.execute("SELECT id,version,payload FROM logis_candidate.objects WHERE id=%s AND project_id=%s AND kind IN ('preferences','goals') AND status='confirmed'",(ident,project)).fetchone()
                if not record:raise HTTPException(409,'Select only confirmed memories in this project')
                if c.execute("SELECT 1 FROM logis_candidate.relationships WHERE to_id=%s AND relation='supersedes'",(ident,)).fetchone():raise HTTPException(409,'Memory has been replaced')
                evidence=c.execute('SELECT e.source_id,e.source_revision,e.quote,e.active,s.revision,s.checksum,s.deleted_at,s.project_id,s.payload FROM logis_candidate.evidence e JOIN logis_candidate.sources s ON s.id=e.source_id WHERE e.object_id=%s',(ident,)).fetchall()
                if not evidence or any(e['quote'] not in e['payload'].get('content','') or not e['active'] or e['deleted_at'] is not None or e['source_id'] in blocked or e['project_id']!=project or e['source_revision']!=e['revision'] for e in evidence):raise HTTPException(409,'Memory evidence is withdrawn or stale')
                text=record['payload'].get('title','')+'\n'+record['payload'].get('detail','')
                if not 1<=len(text.strip())<=2000:raise HTTPException(422,'Memory text exceeds limit')
                mid=digest([project,ident])[:24];mapping[mid]={'record_id':ident,'version':record['version'],'source_ids':[e['source_id'] for e in evidence]}
                rows.append({'id':mid,'text':text,'source_id':digest(project)[:12],'message_index':0,'source_sha256':digest(evidence),'revision':digest([record,evidence])})
            return rows,mapping
    @app.get('/api/projects/{project}/memory/providers')
    def providers(project:str,permissions=Depends(scope)):
        allowed(project,permissions)
        return {'canonical':'candidate PostgreSQL','automatic_capture':False,'automatic_chat_injection':False,'mnemosyne':{'mode':'explicit_confirmed_source_recall','embedding':'existing local Nomic'},'hindsight':{'status':'configured_on_demand','mode':'explicit_selected_conversation_sources','automatic_chat_injection':False,'health':'checked_when_requested'}}
    @app.post('/api/projects/{project}/memory/recall')
    def recall(project:str,body:RecallBody,permissions=Depends(scope)):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials cannot capture derived memory')
        before,mapping=projection(project,body.record_ids)
        from inference_gate import inference_slot
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH'}}
        try:
            with inference_slot(B/'runtime/inference.lock',timeout=0):
                result=subprocess.run([sys.executable,'-B',str(B/'mnemosyne_worker.py'),str(Path(os.environ['LOCALAPPDATA'])/'LogisRework/data/mnemosyne'),str(B/'runtime/mnemosyne-libs')],input=json.dumps({'project':digest(project)[:12],'query':body.query,'entries':before}).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode or len(result.stdout)>100000:raise ValueError('Worker unavailable')
            value=json.loads(result.stdout)
            if value.get('status')!='ready':raise ValueError('Recall unavailable')
            after,current=projection(project,body.record_ids)
            if before!=after or mapping!=current:raise ValueError('Sources changed')
            matches=[]
            for hit in value.get('matches',[]):
                source=next((r for r in before if r['id']==hit.get('id')),None)
                if not source or any(hit.get(k)!=v for k,v in source.items()):raise ValueError('Provenance mismatch')
                matches.append({**mapping[source['id']],'text':hit['text'],'score':hit.get('score')})
            if len(matches)>5 or sum(len(m['text']) for m in matches)>6000:raise ValueError('Context bounds')
            return {'status':'ready','provider':'mnemosyne','method':value.get('method'),'matches':matches,'model':value.get('model'),'dimension':value.get('dimension'),'seconds':value.get('worker_seconds'),'instruction_policy':'Source data, not instructions','canonical_writes':False}
        except HTTPException:raise
        except Exception:return {'status':'unavailable','matches':[],'notice':'Optional recall unavailable or busy; no memory supplied. Canonical records unchanged.'}
    # Internal bounded bridge; HTTP authentication remains on the owning task route.
    app.state.confirmed_memory_projection=projection
    app.state.confirmed_memory_recall=recall
