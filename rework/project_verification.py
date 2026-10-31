"""Durable current-file verification; source is never executed and no model is called."""
import hashlib,json
from source_validation import validate_source

class ProjectVerification:
    def __init__(self,loop):self.loop=loop;loop.verification=self;loop.worker.handlers['local_verify']=self.execute
    def submit(self,project,key,paths,principal):
        if not isinstance(key,str) or not 1<=len(key)<=180 or not isinstance(paths,list) or not 1<=len(paths)<=8:raise ValueError('Bounded key and one to eight explicit files required')
        if not self.loop.authorize({'project':project,'payload':{'_principal':principal}}):raise PermissionError('Current project scope required')
        files=self.loop.files(project);paths=[files.relative(path) for path in paths]
        if len({p.casefold() for p in paths})!=len(paths):raise ValueError('Distinct verification paths required')
        contract=hashlib.sha256(json.dumps([paths,principal],sort_keys=True).encode()).hexdigest();key='verification:'+key
        with self.loop.ledger.connection() as c:row=c.execute('SELECT payload FROM jobs WHERE project=? AND request_key=?',(project,key)).fetchone()
        if row:
            payload=json.loads(row['payload'])
            if payload['_submission']!=contract:raise ValueError('Verification idempotency conflict')
            if payload['_root']!=str(files.root):raise PermissionError('Verification root changed')
        else:
            values=[files.workspace.read(path) for path in paths]
            if sum(v['bytes'] for v in values)>65536:raise ValueError('Verification selection exceeds 64 KB')
            payload={'files':[{k:v[k] for k in ('path','sha256','bytes')} for v in values],'_principal':principal,'_root':str(files.root),'_submission':contract}
        return self.loop.ledger.submit(project,key,'local_verify',payload,max_attempts=1)
    def check(self,attempt):
        attempt.check()
        if self.loop.worker.stop.is_set():raise RuntimeError('Verification worker stopping')
        if not self.loop.authorize(attempt.task):raise PermissionError('Verification scope revoked')
        if str(self.loop.files(attempt.task['project']).root)!=attempt.task['payload']['_root']:raise PermissionError('Verification root changed')
    def execute(self,attempt,files,payload):
        self.check(attempt);checks=[]
        for item in payload['files']:
            self.check(attempt);value=files.workspace.read(item['path'])
            if value['sha256']!=item['sha256']:raise ValueError('Verification snapshot changed; start a new explicit check')
            result=validate_source(item['path'],value['content']);self.check(attempt);files.verify(item['path'],item['sha256'])
            checks.append({'path':item['path'],**result});attempt.checkpoint({'phase':'project_verification','checked':len(checks),'total':len(payload['files'])})
        # Recheck the whole selection after all parser subprocesses finish.
        for item in payload['files']:self.check(attempt);files.verify(item['path'],item['sha256'])
        return {'checks':checks,'passed':all(v['status']=='passed' for v in checks),'read_only':True,'snapshot_versions_rechecked':True,
            'scope':'explicit_selected_files_only','generated_code_executed':False,'semantic_tests_run':False,
            'notice':'Sequentially rechecked snapshot syntax evidence, not an atomic project snapshot, full-project correctness or future file state. No imports, package scripts, generated tests or project commands executed.'},[]
