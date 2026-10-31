"""Explicit adapters for the existing server and run journal; no task writes."""
import task_binding
from evidence_adapters import check_bytes,deliver_preview

def attach_request(database,body,job):
    # The authenticated /api/run handler is the only caller. Tool calls cannot opt in.
    if 'task_id' not in body:return
    binding=task_binding.prepare(database,selected_task_id=body['task_id'],
        selected_project_id=job['_project'],server_job=job,explicit_user_selection=True)
    expected=body.get('task_revision_sha256')
    if expected is not None and expected!=binding['task_revision_sha256']:raise ValueError('Task changed since selection. Refresh task choices and review before sending again.')
    job['task_binding']=binding

def references(database,job):
    if not job.get('task_binding'):return None
    return task_binding.resolve(database,job['task_binding'],job)

def checks(database,job,folder,list_files,safe_file,atomic,now,javascript_check=None):
    refs=references(database,job)
    if refs is None:raise ValueError('Explicit task binding required')
    task,run=refs;items=list_files(folder)
    if len(items)>100:raise ValueError('Bound check limit: 100 files')
    evidence=[]
    for item in items:
        path=item['path'];target=safe_file(folder,path)
        with target.open('rb') as f:data=f.read(120001)
        evidence.append(check_bytes(task,run,path,data,javascript_check))
    references(database,job)  # Do not publish against a changed task.
    value={'time':now(),'kind':'Revision-bound syntax only; unsupported is not passed',
           'status':'failed' if any(e['status']=='failed' for e in evidence) else ('passed' if evidence and all(e['status']=='passed' for e in evidence) else 'unsupported'),
           'results':[{'file':e['artifact']['path'],'status':e['status'],'check':'Captured revision syntax'} for e in evidence],
           'revision_evidence':evidence,'task_id':task['id'],'run_id':run['id']}
    atomic(folder/'checks.json',value)
    return value

def tool_call(database,job,folder,name,args,ordinary,check):
    if job.get('task_binding'):
        try:references(database,job)
        except Exception:
            return {'task_binding_error':True,'error':'Task association changed or unavailable. No tool was executed. Start a new explicitly associated run.'}
        if name=='run_checks':
            try:return check()
            except Exception:return {'task_binding_error':True,'error':'Revision-bound checks could not be verified. No successful check evidence is being reported.'}
    return ordinary(folder,name,args)

def preview(database,job,requested_run,path,data,send_bytes):
    if requested_run!=job.get('id'):raise ValueError('Preview run mismatch')
    refs=references(database,job)
    if refs is None:raise ValueError('Preview run has no explicit task association')
    return deliver_preview(*refs,path,data,send_bytes)
