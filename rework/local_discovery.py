"""Durable bounded project discovery; no inference, source writes or automatic replay."""
import hashlib,json
from collections import deque


def blocked_paths(loop,project):
    with loop.ledger.connection() as c:
        rows=c.execute("SELECT id,status,outputs,CASE WHEN kind='local_plan' THEN payload ELSE '{}' END AS planning FROM jobs WHERE project=? AND status IN ('approval','queued','waiting','running','cancel_requested','needs_review') LIMIT 129",(project,)).fetchall()
    if len(rows)>128:raise ValueError('Too much unresolved work; review saved tasks before planning more')
    result={}
    for row in rows:
        paths=json.loads(row['outputs'])+[item['path'] for item in json.loads(row['planning']).get('files',[])]
        for path in paths:result.setdefault(path.casefold(),[]).append({'task':row['id'],'status':row['status']})
    return result


def completed_match(loop,project,path,sha):
    with loop.ledger.connection() as c:
        row=c.execute("SELECT j.id FROM jobs j JOIN artifacts a ON a.job=j.id WHERE j.project=? AND j.status='completed' AND lower(a.path)=lower(?) AND a.sha256=? ORDER BY j.updated DESC LIMIT 1",(project,path,sha)).fetchone()
    return row['id'] if row else None


class LocalDiscovery:
    def __init__(self,loop):
        self.loop=loop;loop.discovery=self;loop.worker.handlers['local_discovery']=self.execute
    def submit(self,project,key,query,directory,principal):
        if not isinstance(key,str) or not 1<=len(key)<=180 or not isinstance(query,str) or not 1<=len(query)<=200:raise ValueError('Bounded discovery key and literal query required')
        if not self.loop.authorize({'project':project,'payload':{'_principal':principal}}):raise PermissionError('Current project scope required')
        files=self.loop.files(project);directory=files.relative(directory) if directory else ''
        return self.loop.ledger.submit(project,'discovery:'+key,'local_discovery',
            {'query':query,'directory':directory,'_root':str(files.root),'_principal':principal},max_attempts=1)
    def execute(self,attempt,files,payload):
        if str(files.root)!=payload['_root']:raise PermissionError('Discovery root changed')
        queue=deque([payload['directory']]);directories=entries=reads=0;candidates=[];skipped=[];truncated=False
        blocked=blocked_paths(self.loop,attempt.task['project']);needle=payload['query'].casefold()
        while queue and directories<8 and entries<200 and reads<24:
            attempt.check()
            if not self.loop.authorize(attempt.task):raise PermissionError('Discovery scope revoked')
            if str(self.loop.files(attempt.task['project']).root)!=payload['_root']:raise PermissionError('Discovery root changed')
            directory=queue.popleft();directories+=1
            try:page=files.listing(directory,limit=50)
            except PermissionError:raise
            except (OSError,ValueError):
                skipped.append({'path':directory,'reason':'bounded directory unavailable'});truncated=True;continue
            if page['next_cursor']:truncated=True
            for item in page['entries']:
                if entries>=200 or reads>=24:truncated=True;break
                attempt.check();entries+=1
                if item['kind']=='directory':
                    if len(queue)<8:queue.append(item['path'])
                    else:truncated=True
                    continue
                if item['bytes']>12000:
                    skipped.append({'path':item['path'],'reason':'exceeds per-file planning bound'});continue
                if not self.loop.authorize(attempt.task):raise PermissionError('Discovery scope revoked')
                reads+=1
                try:value=files.workspace.read(item['path'])
                except PermissionError:raise
                except (OSError,ValueError):skipped.append({'path':item['path'],'reason':'bounded current text unavailable'});continue
                if value['bytes']>12000:skipped.append({'path':item['path'],'reason':'file grew beyond planning bound'});continue
                filename=needle in item['path'].casefold()
                if not filename and needle not in value['content'].casefold():continue
                completed=completed_match(self.loop,attempt.task['project'],item['path'],value['sha256'])
                candidates.append({'path':item['path'],'sha256':value['sha256'],'bytes':value['bytes'],
                    'match':'filename' if filename else 'content','blocked_by':blocked.get(item['path'].casefold(),[]),'completed_unchanged':completed})
            attempt.checkpoint({'phase':'project_discovery','directories':directories,'entries':entries,'files_read':reads,'matches':len(candidates)})
        if queue:truncated=True
        candidates.sort(key=lambda item:(item['match']!='filename',item['path'].casefold()))
        return {'candidates':candidates,'skipped':skipped[:40],'skipped_truncated':len(skipped)>40,'truncated':truncated,
            'directories':directories,'entries':entries,'files_read':reads,'read_only':True,
            'notice':'Bounded discovery snapshot, not a complete project inventory. Narrow the directory/query if truncated. Current versions and unresolved work are rechecked before planning.'},[]
    def plan(self,project,task_id,version,goal,paths,principal,allow_completed=False):
        task=self.loop.ledger.get(project,task_id)
        if task['kind']!='local_discovery' or task['status']!='completed' or task['version']!=version:raise ValueError('Completed current discovery required')
        if not self.loop.authorize(task):raise PermissionError('Original discovery scope revoked')
        if type(allow_completed) is not bool or not isinstance(paths,list) or not 1<=len(paths)<=2:raise ValueError('Select one or two discovered files')
        files=self.loop.files(project);paths=[files.relative(path) for path in paths]
        if str(files.root)!=task['payload']['_root']:raise PermissionError('Discovery root changed')
        if len({path.casefold() for path in paths})!=len(paths):raise ValueError('Select distinct discoveries')
        candidates={item['path']:item for item in task['result']['candidates']}
        if any(path not in candidates for path in paths):raise ValueError('Only paths in this discovery may be selected')
        planner=getattr(self.loop,'planner',None)
        if planner is None:raise ValueError('Local text-only planner is not configured')
        key='discovery:'+task_id+':'+hashlib.sha256(json.dumps([goal,paths],sort_keys=True).encode()).hexdigest()[:24]
        with self.loop.ledger.connection() as c:existing=c.execute('SELECT id FROM jobs WHERE project=? AND request_key=?',(project,'planning:'+key)).fetchone()
        if not existing:
            blocked=blocked_paths(self.loop,project)
            for path in paths:
                files.verify(path,candidates[path]['sha256'])
                if blocked.get(path.casefold()):raise ValueError('Selected file has unfinished or uncertain work; review it before planning again')
                if completed_match(self.loop,project,path,candidates[path]['sha256']) and not allow_completed:
                    raise ValueError('Selected file matches completed work; explicitly choose a new goal for completed files')
        return planner.submit(project,key,goal,paths,principal,source_discovery=task_id)
