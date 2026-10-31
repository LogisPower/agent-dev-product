"""One typed catalog. Registration is not reachability or a permission grant."""
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Tool:
    description:str
    permission:str='project_read'
    effect:str='read'
    endpoint:str|None=None

TOOLS={
 'system_summary':Tool('One OS total/available memory snapshot; no process or personal fields.','system_summary_read'),
 'service_summary':Tool('Visible service state counts only; no names or configuration.','system_summary_read'),
 'startup_summary':Tool('Visible CIM startup entry count only; incomplete startup coverage.','system_summary_read'),
 'event_summary':Tool('Last24h System critical/error/warning counts, latest32 maximum; no message text or root-cause verdict.','system_summary_read'),
 'setup_checklist':Tool('Collect five bounded C: activity/RAM samples, pause on unsafe/unknown evidence, then create an exact-user fixed checklist. Requires separately granted setup_activity_read and project write.','setup_activity_read','write'),
 'checklist_addon':Tool('Create a new fixed-template offline HTML checklist. path is an explicit .html filename, query is exact user title, text contains 1-12 newline-separated exact user items. No scripts, network or saved checkmarks.','explicit_user','write'),
 'capability_inventory':Tool('Inspect runtime registry and scope without health probes or grants.'),
 'setup_plan':Tool('Propose non-executable setup gates for one exact capability ID; no installs, grants or automatic promotion.'),
 'mcp_clock':Tool('Read host UTC/local clock through the pinned local MCP STDIO server and LangChain tool. No arguments, network or filesystem access.'),
 'clock':Tool('Host date/time with explicit timezone; not an Internet time accuracy check.'),
 'web_search':Tool('Public search followed by bounded page extraction and cited local synthesis. Exact public user query only.','public_query'),
 'web_read':Tool('Read a supplied public HTTP(S) URL with SSRF checks; not an interactive browser.','public_query'),
 'memory_recall':Tool('Recall current source-backed assertions in this project, query optional.'),
 'memory_save':Tool('Save an exact explicit user assertion, not an inferred fact.','explicit_user','write'),
 'memory_correct':Tool('Correct one uniquely identified assertion from an explicit user request.','explicit_user','write'),
 'memory_forget':Tool('Archive one explicit assertion; history remains.','explicit_user','write'),
 'project_files':Tool('List or search selected project imported filenames; query filters names.','project_read','read','/api/projects/{project}/files'),
 'file_read':Tool('Read bounded UTF-8 current imported-file revision using file_id from project_files.','project_read','read','/api/projects/{project}/files/{key}'),
 'file_edit':Tool('Save an explicitly supplied replacement text as a separate file revision, with exact file_id and expected_sha256. Originals preserved.','explicit_user','write','/api/projects/{project}/files/{key}'),
 'project_records':Tool('Read current selected-project tasks/decisions/preferences/goals; query filters titles/details.','project_read','read','/api/projects/{identifier}/objects'),
 'task_status':Tool('Read durable run states in this project; optional exact run_id. No automatic resume.'),
 'task_cancel':Tool('Request cancellation of one existing chat run explicitly named by user; active inference is nonpreemptive.','explicit_user','write','/api/projects/{project}/chat/runs/{run}/cancel'),
 'task_retry':Tool('Retry one explicitly named failed chat run through existing idempotency and source checks.','explicit_user','write','/api/projects/{project}/chat/runs/{failed_run}/retry'),
 'artifact_list':Tool('List generated offline HTML revisions and recorded check status.','project_read','read','/api/projects/{project}/builds'),
 'artifact_read':Tool('Read a completed project HTML artifact by run_id; verify saved hash before returning.'),
 'artifact_check':Tool('Recheck saved HTML policy and JavaScript syntax; does not execute generated code or prove browser behavior.'),
 'build_html':Tool('Create/revise a tiny offline single-file HTML app on explicit user request. Uses exact request; never executes generated code on host.','explicit_user','write'),
 'workspace_read':Tool('Read one current UTF-8 file page in the approved project partition. Use offset and expected_sha256 for subsequent pages. Missing returns discovery guidance; do not guess filenames.','project_read'),
 'workspace_list':Tool('List one approved project directory. Empty path means root; cursor continues a version-checked page. Discover paths before reads.','project_read'),
 'workspace_search':Tool('Literal filename/content search within one directory of approved project workspace; bounded, nonrecursive, cursor-paged.','project_read'),
 'workspace_create':Tool('Create a new explicitly named UTF-8 file; never overwrite.','explicit_user','write'),
 'workspace_edit':Tool('Edit a named workspace file with expected hash and recovery copy.','explicit_user','write'),
 'workspace_move':Tool('Move a named workspace file within this project; no overwrite; recovery receipt.','explicit_user','write'),
 'network_interfaces':Tool('Local interface metadata, not external reachability.','network_read'),
 'network_routes':Tool('Read up to128 local route records; no changes.','network_read'),
 'network_dns':Tool('Read configured DNS server metadata; no resolver changes.','network_read'),
 'network_connectivity':Tool('One TCP handshake to an exact approved IP/port; no scan.','network_read'),
 'disk_capacity':Tool('Read C: total/free bytes; no scan or cleanup.','disk_read'),
 'disk_activity':Tool('Five bounded C: latency/queue/activity and paging samples; no file attribution.','disk_read'),
 'disk_process_io':Tool('Top ten short process-wide I/O counter observations; not C:-specific or file attribution.','disk_read'),
 'disk_trace_plan':Tool('Prepare an exact bounded file-level trace proposal. No executor; separate administrator approval required.','disk_read'),
 'listeners':Tool('Bounded current TCP listeners and UDP endpoints with process names when permitted. No command lines, remote connections, scans or changes.','local_metadata'),
}

# Authoritative model-facing argument schema, shared with validation. No shell or
# generic path argument exists. Build text comes from the authoritative request.
FIELDS={
 'offset':{'type':'integer','minimum':0,'maximum':131072},
 'cursor':{'type':'string','maxLength':1024},
 'port':{'type':'integer','minimum':1,'maximum':65535},
 'path':{'type':'string','maxLength':180},'destination':{'type':'string','maxLength':180},
 'query':{'type':'string','maxLength':500},'text':{'type':'string','maxLength':6000},
 'kind':{'type':'string','enum':['preferences','goals','decisions','tasks']},
 'timezone':{'type':'string','maxLength':100},
 'file_id':{'type':'string','pattern':'^[a-f0-9]{64}$'},
 'run_id':{'type':'string','pattern':'^[a-f0-9]{32}$'},
 'expected_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
}
ARGS={
 'system_summary':([],[]),'service_summary':([],[]),'startup_summary':([],[]),'event_summary':([],[]),
 'setup_checklist':(['path','query','text'],['path','query','text']),
 'checklist_addon':(['path','query','text'],['path','query','text']),
 'capability_inventory':([],[]),'setup_plan':(['query'],['query']),
 'disk_capacity':([],[]),'disk_activity':([],[]),'disk_process_io':([],[]),'disk_trace_plan':([],[]),
 'network_interfaces':([],[]),'network_routes':([],[]),'network_dns':([],[]),'network_connectivity':(['query','port'],['query','port']),
 'workspace_read':(['path','offset','expected_sha256'],['path']),
 'workspace_list':(['path','cursor'],[]),'workspace_search':(['path','query','cursor'],['query']),
 'workspace_create':(['path','text'],['path','text']),
 'workspace_edit':(['path','text','expected_sha256'],['path','text','expected_sha256']),
 'workspace_move':(['path','destination','expected_sha256'],['path','destination','expected_sha256']),
 'mcp_clock':([],[]),'clock':(['timezone'],[]),'web_search':(['query'],['query']),'web_read':(['query'],['query']),
 'memory_recall':(['query'],[]),'memory_save':(['text','kind'],['text']),
 'memory_correct':(['query','text'],['query','text']),'memory_forget':(['query'],['query']),
 'project_files':(['query'],[]),'file_read':(['file_id'],['file_id']),
 'file_edit':(['file_id','expected_sha256','text'],['file_id','expected_sha256','text']),
 'project_records':(['query'],[]),'task_status':(['run_id'],[]),
 'task_cancel':(['run_id'],['run_id']),'task_retry':(['run_id'],['run_id']),
 'artifact_list':([],[]),'artifact_read':(['run_id'],['run_id']),
 'artifact_check':(['run_id'],['run_id']),'build_html':(['run_id','expected_sha256'],[]),'listeners':([],[]),
}
def argument_schema(name):
    fields,required=ARGS[name]
    properties={'tool':{'const':name},**{k:dict(FIELDS[k]) for k in fields}}
    if name.startswith('memory_') and 'text' in properties:properties['text']['maxLength']=2000
    return {'type':'object','properties':properties,'required':['tool',*required],'additionalProperties':False}

def planner_schema():
    return {'type':'object','properties':{'goal':{'enum':['answer','plan','action','clarify']},'answer':{'type':'string','maxLength':64000},'actions':{'type':'array','maxItems':3,'items':{'oneOf':[argument_schema(n) for n in TOOLS]}}},'additionalProperties':False}

def endpoint(app,path,method='GET'):
    return next((r.endpoint for r in app.routes if getattr(r,'path',None)==path and method in getattr(r,'methods',())),None)

def catalog(app,permissions=None):
    result={}
    for name,spec in TOOLS.items():
        registered=True
        if name=='mcp_clock':
            from mcp_bridge import configured
            registered=configured()
        if spec.endpoint:registered=endpoint(app,spec.endpoint,'POST' if spec.effect=='write' else 'GET') is not None
        if name.startswith('web_'):registered=callable(getattr(app.state,'intent_research',None))
        if name=='build_html':registered=callable(getattr(app.state,'chat_build',None))
        if name=='file_edit':registered=registered and callable(getattr(app.state,'chat_file_edit',None))
        if name=='task_retry':registered=registered and callable(getattr(app.state,'chat_retry',None))
        if name in ('artifact_read','artifact_check'):registered=endpoint(app,'/api/projects/{project}/builds') is not None
        if name.startswith('workspace_') or name in ('checklist_addon','setup_checklist'):
            from workspace_facade import enabled
            registered=os.name=='nt' and (enabled() or (name.startswith('workspace_') and callable(getattr(app.state,'project_files',None))))
        if name.startswith('disk_'):registered=os.name=='nt'
        if name=='listeners':registered=os.name=='nt'
        if name in ('system_summary','service_summary','startup_summary','event_summary'):registered=os.name=='nt'
        authorized=None if permissions is None else bool(permissions.get('write')) if spec.effect=='write' else True
        # Host metadata is owner-only, never conferred by a project credential.
        if name=='listeners':authorized=None if permissions is None else permissions.get('owner') is True
        if name.startswith('network_'):authorized=None if permissions is None else permissions.get('network_read') is True
        if name=='network_connectivity':authorized=None if permissions is None else permissions.get('network_read') is True and bool(permissions.get('network_endpoints'))
        if name.startswith('disk_'):authorized=None if permissions is None else permissions.get('disk_read') is True or (name=='disk_activity' and permissions.get('setup_activity_read') is True)
        if name in ('system_summary','service_summary','startup_summary','event_summary'):
            from system_summary import authorized as summary_authorized
            authorized=None if permissions is None else summary_authorized(name,permissions)
        if name=='setup_checklist':authorized=None if permissions is None else permissions.get('write') is True and permissions.get('setup_activity_read') is True
        result[name]={'installed':True,'registered':registered,'enabled':registered,'authorized':authorized,
          'reachable':'not_probed','tested':'see release evidence; not a live probe','effect':spec.effect,'permission':spec.permission,'description':spec.description,'arguments':argument_schema(name)}
    result['mcp']={k:result['mcp_clock'][k] for k in ('installed','registered','enabled','authorized','reachable')}
    result['mcp']['description']='Pinned isolated MCP2.3.0 STDIO clock only through LangChain. Legacy SDK access remains unresolved; no arbitrary servers/tools.'
    result['paperclip']={'installed':True,'registered':False,'enabled':False,'authorized':False,'reachable':'not_probed','description':'Stopped; queue inspection and rework adapter pending. No workers started.'}
    return result
