"""Canonical source-backed chat memory; caller transaction owns receipt and reply."""
import datetime,uuid,hashlib,json
from psycopg.types.json import Jsonb

def current(c,project):
    p=c.execute('SELECT archived,context_policy FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
    if not p or p['archived'] or p['context_policy'].get('learning',True) is False:raise ValueError('Project memory is unavailable or opted out')
    return c.execute("""SELECT o.id,o.kind,o.status,o.version,o.payload,e.source_id,e.source_revision,e.quote
    FROM logis_candidate.objects o JOIN logis_candidate.evidence e ON e.object_id=o.id
    JOIN logis_candidate.sources s ON s.id=e.source_id
    WHERE o.project_id=%s AND o.status IN ('confirmed','open') AND o.kind IN ('preferences','goals','decisions','tasks')
    AND s.project_id=%s AND s.deleted_at IS NULL AND e.active AND e.source_revision=s.revision
    AND position(e.quote in coalesce(s.payload->>'content',''))>0
    AND NOT EXISTS(SELECT 1 FROM logis_candidate.relationships r WHERE r.to_id=o.id AND r.relation='supersedes')
    AND NOT EXISTS(SELECT 1 FROM logis_candidate.sources t WHERE t.project_id=o.project_id AND t.kind='memory_tombstone' AND t.payload->>'source_id'=s.id)
    ORDER BY o.updated_at DESC LIMIT 100""",(project,project)).fetchall()

def execute(c,project,action,user_id,run):
    rows=current(c,project)
    # No model chooses an implicit mutation target. Unique exact phrase or ID only.
    selected={r['id']:r for r in rows if action.query and (action.query==r['id'] or action.query.casefold() in (r['payload'].get('title','')+' '+r['payload'].get('detail','')).casefold())}
    if action.tool=='memory_recall':
        matches=list(selected.values())[:5] if action.query else rows[:5]
        return {'status':'read','answer':'\n'.join(r['payload'].get('detail',r['payload'].get('title',''))+' [record '+r['id']+', source '+r['source_id']+', revision '+str(r['source_revision'])+']' for r in matches) or 'No matching current source-backed records in this project.','matches':[{'id':r['id'],'source_id':r['source_id'],'revision':r['source_revision']} for r in matches],'verification':'user assertions with current source evidence; not independently verified facts','conflicts':'Multiple matching assertions; no automatic reconciliation' if len(matches)>1 else 'not assessed'}
    if action.tool in ('memory_correct','memory_forget') and len(selected)!=1:raise ValueError('Name one unique current memory phrase or record ID; nothing changed')
    source=c.execute('SELECT s.id,s.revision,s.payload FROM logis_candidate.messages m JOIN logis_candidate.sources s ON s.id=m.source_id WHERE m.id=%s AND m.project_id=%s AND m.role=\'user\' AND s.deleted_at IS NULL',(user_id,project)).fetchone()
    if not source:raise ValueError('User source unavailable')
    if action.tool!='memory_forget' and action.text not in source['payload'].get('content',''):raise ValueError('Source excerpt changed')
    if action.tool=='memory_save':
        duplicate=next((r for r in rows if r['payload'].get('detail')==action.text and r['kind']==action.kind),None)
        if duplicate:return {'status':'already_saved','record_id':duplicate['id'],'answer':'Already saved in this project; no duplicate created.'}
        # Explicit conflicting facts are not silently merged. Corrections require target.
    old=next(iter(selected.values())) if selected else None
    if old and action.tool in ('memory_correct','memory_forget'):
        c.execute("UPDATE logis_candidate.objects SET status='archived',version=version+1,updated_at=now() WHERE id=%s AND version=%s",(old['id'],old['version']))
        c.execute('UPDATE logis_candidate.evidence SET active=false WHERE object_id=%s',(old['id'],))
    if action.tool=='memory_forget':
        ident=old['id'];kind=old['kind'];answer='Removed this record from active recall. The original conversation and audit history remain.';status='forgotten'
    else:
        ident=uuid.uuid4().hex;kind=old['kind'] if old and action.tool=='memory_correct' else action.kind
        observed=datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload={'title':action.text[:180],'detail':action.text,'speaker':'user','observed_at':observed,'effective_at':None,'verification_status':'user_asserted','explicit_capture':True,'source_revision':source['revision']}
        state='confirmed' if kind in ('preferences','goals') else 'open'
        c.execute('INSERT INTO logis_candidate.objects(id,kind,project_id,status,payload) VALUES(%s,%s,%s,%s,%s)',(ident,kind,project,state,Jsonb(payload)))
        c.execute('INSERT INTO logis_candidate.evidence VALUES(%s,%s,%s,%s,true)',(ident,source['id'],source['revision'],action.text))
        if old and action.tool=='memory_correct':c.execute("INSERT INTO logis_candidate.relationships VALUES(%s,%s,'supersedes')",(ident,old['id']))
        answer='Saved your explicit '+('correction' if action.tool=='memory_correct' else 'record')+' in this project with source evidence. Recorded as your assertion, not independent verification.';status='saved'
    event=uuid.uuid4().hex;fingerprint=hashlib.sha256(action.model_dump_json().encode()).hexdigest()
    c.execute('INSERT INTO logis_candidate.events(event_id,event_type,object_id,actor_id,correlation_id,permissions_scope,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)',(event,kind+'.updated' if old else kind+'.created',ident,'local-user','chat-intent:'+run,project,Jsonb({'operation':action.tool,'request_hash':fingerprint,'version':old['version']+1 if action.tool=='memory_forget' else 1})))
    c.execute('INSERT INTO logis_candidate.outbox(event_id) VALUES(%s)',(event,))
    return {'status':status,'record_id':ident,'source_id':source['id'],'answer':answer}
