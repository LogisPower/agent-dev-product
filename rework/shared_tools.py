"""Scoped adapters reused by ordinary chat, with bounded evidence receipts."""
import json,hashlib,re,datetime
from tool_catalog import TOOLS,endpoint,catalog

def receipt(name,data,answer=None,status='read',effect='none'):
    raw=json.dumps(data,ensure_ascii=False,default=str)
    if len(raw)>24000:raise ValueError('Tool result exceeds context bound; narrow the request')
    return {'tool':name,'status':status,'effect':effect,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'data':data,'evidence_sha256':hashlib.sha256(raw.encode()).hexdigest(),
      'answer':answer or name+' result (selected project only):\n'+raw}

def execute(app,db,project,action,permissions,run,model,timezone=None):
    if project not in permissions.get('projects',[]):raise PermissionError('Project not authorized')
    name=action.tool;spec=TOOLS[name]
    state=catalog(app,permissions)[name]
    if not state['registered']:raise ValueError(name+' unavailable: handler not registered')
    if not state['authorized']:raise PermissionError(name+' is not authorized for this credential; no action executed')
    if name in ('system_summary','service_summary','startup_summary','event_summary'):
        from system_summary import collect
        value=collect(name,permissions)
        return {**receipt(name,value,answer=name+' bounded host summary: '+json.dumps(value),status=value['status']),'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_scoped':True}}
    if name=='setup_checklist':
        from setup_admission import execute as setup
        value=setup(db,project,action,permissions,run)
        return {**receipt(name,value,value.get('notice'),status=value['status'],effect=value['effect']),'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_scoped':True}}
    if name=='checklist_addon':
        from checklist_addon import execute as create_addon
        value=create_addon(db,project,action,permissions,run)
        return {**receipt(name,value,'Offline checklist saved and exact bytes read back. Checkmarks are not saved; no code was executed and browser behavior is untested.',status='verified',effect='workspace_file'),'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_scoped':True}}
    if name in ('capability_inventory','setup_plan'):
        from setup_workflow import inventory,propose
        value=inventory(app,permissions) if name=='capability_inventory' else propose(app,permissions,action.query)
        return {**receipt(name,value,status='read' if name=='capability_inventory' else 'proposed'),'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_scoped':True}}
    if name.startswith('disk_'):
        from disk_diagnostics import collect,trace_plan
        value=trace_plan(project,permissions) if name=='disk_trace_plan' else collect(name,permissions)
        return {**receipt(name,value,status='proposed' if name=='disk_trace_plan' else 'read'),'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_scoped':True}}
    if name.startswith('network_'):
        from network_read import metadata,connectivity
        value=connectivity(action.query,action.port,permissions) if name=='network_connectivity' else metadata(name,permissions)
        return receipt(name,value)
    if name.startswith('workspace_'):
        from workspace_facade import execute as workspace_execute
        value=workspace_execute(db,project,action,permissions,run,files_resolver=getattr(app.state,'project_files',None))
        reading=name in ('workspace_read','workspace_list','workspace_search')
        return receipt(name,value,status='read' if reading else 'verified',effect='none' if reading else 'workspace_file')
    if name=='mcp_clock':
        from mcp_bridge import invoke_clock
        from mcp_cancel import current
        value=invoke_clock(current(run).is_set)
        return {**receipt(name,value,answer='MCP host clock: '+value['result']['host_time']+' ('+value['result']['host_timezone']+'); UTC '+value['result']['utc']+'. Clock accuracy is not independently verified.',status='read'),'actor':{'initiated_by':'logis_dispatcher','run_id':run,'project_scoped':True}}
    if name=='clock':
        from intent_core import clock
        return {'tool':name,**clock(action.timezone or timezone)}
    if name in ('web_search','web_read'):return {'tool':name,**app.state.intent_research(action,run,model)}
    if name=='memory_recall':
        from intent_memory import execute as recall
        with db() as c:return {'tool':name,**recall(c,project,action,None,run)}
    if name=='listeners':
        from local_diagnostics import listeners
        return {'tool':name,**listeners(permissions)}
    if name=='project_files':
        items=endpoint(app,spec.endpoint)(project,permissions)
        selected=[{k:v for k,v in item.items() if k in ('id','name','bytes','sha256')} for item in items if action.query.casefold() in item['name'].casefold()]
        return receipt(name,{'files':selected[:60],'truncated':len(selected)>60,'scope':'imported project files; not arbitrary host files'})
    if name=='file_read':
        value=endpoint(app,spec.endpoint)(project,action.file_id,permissions)
        if len(value.get('content',''))>16000:raise ValueError('File exceeds chat reading bound; use file viewer or a smaller source')
        return receipt(name,{k:v for k,v in value.items() if k in ('id','name','content','sha256','revision','source_sha256')})
    if name=='file_edit':
        from candidate_files import Edit
        value=app.state.chat_file_edit(project,action.file_id,Edit(content=action.text,expected_sha256=action.expected_sha256),permissions,run)
        return receipt(name,value,'File revision saved with a checked hash; the imported original was preserved. Code was not executed.',status='unchanged' if value.get('unchanged') else 'committed',effect='file_revision')
    if name=='project_records':
        items=endpoint(app,'/api/projects/{identifier}/objects')(project,permissions)
        selected=[x for x in items if x['status']!='archived' and action.query.casefold() in json.dumps(x.get('payload',{})).casefold()]
        return receipt(name,{'records':selected[:25],'truncated':len(selected)>25,'verification':'Recorded project state; assertions are not automatically facts'})
    if name=='task_status':
        with db() as c:
            rows=c.execute("SELECT id,agent_id,status,payload FROM logis_candidate.runs WHERE project_id=%s AND id<>%s AND (%s='' OR id=%s) ORDER BY CASE WHEN status IN ('running','queued','dispatching') THEN 0 ELSE 1 END,id LIMIT 50",(project,run,action.run_id,action.run_id)).fetchall()
        # Do not dump internal prompts or message history into a status tool.
        data=[{'id':x['id'],'kind':x['agent_id'],'status':x['status'],'phase':x['payload'].get('harness_phase'),'notice':x['payload'].get('notice'),'cancel_requested':x['payload'].get('cancel_requested',False)} for x in rows]
        return receipt(name,{'runs':data,'ordering':'Active work first, then IDs; not chronological. Current status query excluded.','automatic_resume':False})
    if name=='artifact_list':
        rows=endpoint(app,spec.endpoint)(project,permissions)
        return receipt(name,[{'id':x['id'],'status':x['status'],**{k:v for k,v in x['payload'].items() if k in ('sha256','bytes','checks','parent_run','created_at')}} for x in rows[:25]])
    if name in ('artifact_read','artifact_check'):
        with db() as c:row=c.execute("SELECT payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s AND agent_id='local-build' AND status='completed'",(action.run_id,project)).fetchone()
        if not row:raise ValueError('No completed artifact with that ID in this project')
        from candidate_build import artifact,validate_html
        path=artifact(action.run_id)
        if path.stat().st_size>18000:raise ValueError('Artifact read bound')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['payload'].get('sha256'):raise ValueError('Saved artifact hash mismatch')
        text=raw.decode('utf-8')
        return receipt(name,{'run_id':action.run_id,'sha256':hashlib.sha256(raw).hexdigest(),**({'checks':validate_html(text)} if name=='artifact_check' else {'html':text})})
    if name=='build_html':
        from candidate_build import BuildBody
        value=app.state.chat_build(project,BuildBody(prompt=action.text,parent_run=action.run_id or None,parent_sha256=action.expected_sha256 or None),'chat-build-'+run,permissions,run)
        return receipt(name,value,'Build '+value['status']+'. '+('Saved hash and syntax checks are in the receipt; browser behavior is not yet verified.' if value['status']=='completed' else 'Inspect the task before retry; success is not claimed.'),status=value['status'],effect='artifact_revision' if value['status']=='completed' else 'inspect_outcome')
    if name in ('task_cancel','task_retry'):
        fn=endpoint(app,spec.endpoint,'POST')
        if action.run_id==run:raise ValueError('Cannot control the current dispatch run')
        value=app.state.chat_retry(project,action.run_id,'tool-retry-'+run,permissions,run) if name=='task_retry' else fn(project,action.run_id,permissions=permissions)
        return receipt(name,value,'Task control recorded: '+value['status']+'. No immediate provider interruption or automatic side-effect replay is promised.',status='requested' if value['status']=='running' else value['status'],effect='task_control')
    raise ValueError('Unsupported execution adapter')
