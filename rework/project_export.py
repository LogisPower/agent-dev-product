"""Bounded, coherent canonical export. No filesystem or credential store access."""
import hashlib,json
from fastapi import Depends,HTTPException
from fastapi.responses import Response

MAX_ROWS=1000
MAX_BYTES=2*1024*1024

def register(app,db,scope,allowed):
    @app.get('/api/projects/{project}/export')
    def export(project:str,permissions=Depends(scope)):
        allowed(project,permissions)
        with db(snapshot=True) as c:
            # Scope checks happen outside the snapshot; all exported canonical
            # sections are read from one immutable PostgreSQL MVCC snapshot.
            row=c.execute("SELECT id,name,archived,context_policy,legacy_payload->>'brief' AS brief,coalesce((legacy_payload->>'_ui_trashed')::boolean,false) AS trashed FROM logis_candidate.projects WHERE id=%s",(project,)).fetchone()
            if not row:raise HTTPException(404,'Project not found')
            policy=row['context_policy'];row['context_policy']={k:policy[k] for k in ('learning','mnemosyne') if k in policy}
            row['context_policy']['sources']=[x for x in policy.get('sources',[]) if x in permissions.get('projects',[])]
            sections={
                'messages':"SELECT m.id,m.source_id,m.legacy_index,m.role,m.content FROM logis_candidate.messages m JOIN logis_candidate.sources s ON s.id=m.source_id WHERE m.project_id=%s AND s.deleted_at IS NULL ORDER BY m.legacy_index",
                'sources':"SELECT id,kind,checksum,revision,payload->>'content' AS content FROM logis_candidate.sources WHERE project_id=%s AND deleted_at IS NULL ORDER BY id",
                'records':"SELECT id,kind,version,status,payload,updated_at FROM logis_candidate.objects WHERE project_id=%s ORDER BY id",
                'evidence':"SELECT e.object_id,e.source_id,e.source_revision,e.quote,e.active FROM logis_candidate.evidence e JOIN logis_candidate.objects o ON o.id=e.object_id JOIN logis_candidate.sources s ON s.id=e.source_id WHERE o.project_id=%s AND s.project_id=o.project_id AND s.deleted_at IS NULL ORDER BY e.object_id,e.source_id,e.quote",
                'relationships':"SELECT r.from_id,r.to_id,r.relation FROM logis_candidate.relationships r JOIN logis_candidate.objects a ON a.id=r.from_id JOIN logis_candidate.objects b ON b.id=r.to_id WHERE a.project_id=%s AND b.project_id=a.project_id ORDER BY r.from_id,r.to_id,r.relation",
                'runs':"SELECT id,agent_id,status,jsonb_build_object('sha256',payload->'sha256','bytes',payload->'bytes','checks',payload->'checks','file',payload->'file','created_at',payload->'created_at','harness_phase',payload->'harness_phase','cancel_requested',payload->'cancel_requested') AS evidence FROM logis_candidate.runs WHERE project_id=%s ORDER BY id"
            }
            data={'format':'logis-canonical-export-v1','project':row,'snapshot_at':c.execute('SELECT transaction_timestamp() AS value').fetchone()['value'],'sections':{}}
            budget=0
            for name,sql in sections.items():
                size=c.execute('SELECT count(*) AS rows,coalesce(sum(octet_length(to_jsonb(q)::text)),0) AS bytes FROM ('+sql+') q',(project,)).fetchone()
                budget+=int(size['bytes'])
                if size['rows']>MAX_ROWS or budget>MAX_BYTES:raise HTTPException(413,'Project exceeds bounded export size; no partial export was produced')
                data['sections'][name]=c.execute(sql,(project,)).fetchall()
            data['manifest']={'counts':{k:len(v) for k,v in data['sections'].items()},'complete_for_listed_sections':True,'filesystem_backup':False,'excluded':['filesystem file bytes','provider prompts and compaction archives','credentials and device sessions','withdrawn source messages and evidence','cross-project relationships and inaccessible context-source IDs'],'bounds':{'rows_per_section':MAX_ROWS,'bytes':MAX_BYTES}}
            raw=json.dumps(data,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode('utf-8')
            if len(raw)>MAX_BYTES:raise HTTPException(413,'Project exceeds bounded export size; no partial export was produced')
            return Response(raw,media_type='application/json',headers={'Content-Disposition':'attachment; filename="logis-canonical-export.json"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Content-SHA256':hashlib.sha256(raw).hexdigest()})
