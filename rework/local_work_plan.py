"""Atomic, bounded plans of exact edits. No inference, approval or execution here."""
import hashlib
import re
from durable_tasks import encoded


def plan_identifier(project,key):
    return hashlib.sha256(encoded([project,key]).encode()).hexdigest()[:32]


def submit_plan(loop,project,key,title,steps,principal):
    if not isinstance(key,str) or not 1<=len(key)<=180 or not isinstance(title,str) or not title.strip() or len(title)>120:
        raise ValueError('Bounded plan key and title required')
    if not isinstance(steps,list) or not 1<=len(steps)<=8:
        raise ValueError('A plan requires one to eight steps')
    if not loop.authorize({'project':project,'payload':{'_principal':principal}}):
        raise PermissionError('Current plan scope required')
    files=loop.files(project);names=set();paths=set();normalized=[]
    for step in steps:
        if not isinstance(step,dict) or set(step)!={'name','edit','after'}:
            raise ValueError('Named step, exact edit and predecessor names required')
        name,after=step['name'],step['after']
        if not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,39}',name) or name in names:
            raise ValueError('Unique bounded step names required')
        if not isinstance(after,list) or len(after)>8 or any(not isinstance(x,str) or x not in names for x in after) or len(after)!=len(set(after)):
            raise ValueError('Dependencies must name distinct earlier steps in this plan')
        if not isinstance(step['edit'],dict) or 'path' not in step['edit']:raise ValueError('Exact file edit required')
        edit=dict(step['edit']);path=files.relative(edit['path']);edit['path']=path
        if path.casefold() in paths:raise ValueError('Use one planned edit per file; combine changes before submission')
        names.add(name);paths.add(path.casefold());normalized.append({'name':name,'edit':edit,'after':after})
    # The whole immutable contract is included in every job's idempotency check.
    contract=hashlib.sha256(encoded({'title':title,'steps':normalized,'principal':principal}).encode()).hexdigest()
    plan_id=plan_identifier(project,key)
    created={};tasks=[]
    with loop.ledger.transaction() as connection:
        for position,step in enumerate(normalized,1):
            dependencies=[{'task':created[n]['id'],'path':created[n]['payload']['targets'][0]['path']} for n in step['after']]
            metadata={'id':plan_id,'title':title,'name':step['name'],'position':position,'total':len(steps),'after':step['after'],'contract':contract}
            task=loop.submit(project,'plan:'+plan_id+':'+step['name'],[step['edit']],principal=principal,
                dependencies=dependencies,_connection=connection,_plan=metadata)
            created[step['name']]=task;tasks.append(task)
    return {'id':plan_id,'title':title,'tasks':tasks,'approval_required':True,'started':False}
