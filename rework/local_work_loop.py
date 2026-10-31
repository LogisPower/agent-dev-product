"""Opt-in durable exact-edit handoffs; no credentials, RPC defaults or auto-start.

A trusted transport supplies bounded submit/poll/cancel calls for an existing local
provider. This module verifies selected files; it is not an OS permission sandbox.
Use a separate private ledger and an isolated workspace, not the Foundation ledger.
"""
import contextlib
import hashlib
import json
import re
import time
from pathlib import Path
from durable_tasks import Ledger
from project_files import ProjectFiles
from task_worker import Worker


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class LocalWorkLoop:
    def __init__(self, state_path, resolve_project, authorize, transport, *, timeout=600):
        if not callable(resolve_project) or not callable(authorize):
            raise ValueError('Explicit current-scope resolver and authorizer required')
        if not all(callable(getattr(transport, name, None)) for name in ('submit', 'poll', 'cancel')):
            raise ValueError('Bounded local transport required')
        if type(timeout) not in (int, float) or not 1 <= timeout <= 1800:
            raise ValueError('Bounded handoff timeout required')
        if not Path(state_path).parent.is_dir():
            raise ValueError('Private state directory must already exist')
        self.ledger=Ledger(state_path)
        self.resolve_project,self.authorize,self.transport=resolve_project,authorize,transport
        self.timeout=timeout
        self.worker=Worker(self.ledger,{'local_exact_edit':self._execute},self.files,authorize)

    def files(self, project):
        files=ProjectFiles(self.resolve_project(project))
        if self.ledger.path.absolute().is_relative_to(files.root):
            raise PermissionError('Local task state must stay outside model-writable files')
        return files

    def submit(self, project, key, edits, *, principal, dependencies=(), _connection=None, _plan=None):
        """Record bounded exact replacements for explicit approval; no model call."""
        if not isinstance(edits,list) or not 1 <= len(edits) <= 4:
            raise ValueError('One to four exact file edits required')
        if not self.authorize({'project':project,'payload':{'_principal':principal}}):
            raise PermissionError('Current local work scope required')
        files=self.files(project);targets=[];seen=set()
        submission=hashlib.sha256(json.dumps({'edits':edits,'principal':principal,'dependencies':dependencies,**({'plan':_plan} if _plan is not None else {})},sort_keys=True).encode()).hexdigest()
        with (contextlib.nullcontext(_connection) if _connection is not None else self.ledger.connection()) as connection:
            existing=connection.execute('SELECT payload FROM jobs WHERE project=? AND request_key=?',(project,key)).fetchone()
        if existing:
            payload=json.loads(existing['payload'])
            if payload.get('_submission')!=submission:raise ValueError('Local handoff idempotency conflict')
            return self.ledger.submit(project,key,'local_exact_edit',payload,
                outputs=[t['path'] for t in payload['targets']],dependencies=dependencies,approval=True,max_attempts=1,_connection=_connection)
        for edit in edits:
            if set(edit) != {'path','expected_sha256','old','new'}:
                raise ValueError('Exact path, version and replacement fields required')
            path=files.relative(edit['path'])
            if path.casefold() in seen:raise ValueError('Duplicate target')
            seen.add(path.casefold())
            if not isinstance(edit['expected_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',edit['expected_sha256']):
                raise ValueError('Expected current file hash required')
            old,new=edit['old'],edit['new']
            if not isinstance(old,str) or not old or not isinstance(new,str) or len((old+new).encode())>32768 or old==new:
                raise ValueError('Bounded nonempty changing replacement required')
            # Read validation is intentionally repeated before dispatch. Preserve CRLF.
            current=files.workspace.read(path)
            if current['sha256']!=edit['expected_sha256'] or current['content'].count(old)!=1:
                raise ValueError('Stale version or ambiguous anchor')
            after=current['content'].replace(old,new,1)
            if len(after.encode())>131072:raise ValueError('Result exceeds file bound')
            targets.append({**edit,'path':path,'result_sha256':digest(after)})
        return self.ledger.submit(project,key,'local_exact_edit',{'targets':targets,'_principal':principal,'_submission':submission,'_root':str(files.root),'_plan':_plan},
            outputs=[t['path'] for t in targets],dependencies=dependencies,approval=True,max_attempts=1,_connection=_connection)

    def approve(self, project, task, version):
        value=self.ledger.get(project,task)
        if not self.authorize(value):raise PermissionError('Scope withdrawn')
        self.files(project)
        return self.ledger.approve(project,task,version)

    def _observation(self, request):
        value=self.transport.poll(request)
        if not isinstance(value,dict) or value.get('request_id')!=request or value.get('status') not in ('queued','running','completed','failed','canceled'):
            raise ValueError('Unverified provider request status')
        return value

    def _status(self, request):return self._observation(request)['status']

    def _evidence(self, task, files):
        if not self.authorize(task):raise PermissionError('Scope withdrawn')
        if str(self.files(task['project']).root)!=task['payload']['_root'] or str(files.root)!=task['payload']['_root']:
            raise PermissionError('Workspace binding changed')
        return [files.verify(t['path'],t['result_sha256']) for t in task['payload']['targets']]

    def _execute(self, attempt, files, payload):
        request=attempt.task['id']
        if str(files.root)!=payload['_root']:raise PermissionError('Workspace binding changed')
        for target in payload['targets']:files.verify(target['path'],target['expected_sha256'])
        if not self.authorize(attempt.task):raise PermissionError('Scope withdrawn')
        from local_planning_context import planning_context
        history=planning_context(self,attempt.task['project'],[t['path'] for t in payload['targets']],exclude_id=request)
        packet={'request_id':request,'project':attempt.task['project'],'targets':payload['targets'],'planning_evidence':history,
            'instructions':'Apply only these exact replacements in the caller-bound isolated workspace. Check versions first. Stop on mismatch. No other files, commands, agents, credentials, permissions, services or model changes. Read back targets; do not claim tests were run.'}
        try:
            prepare=getattr(self.transport,'prepare',None)
            if callable(prepare):prepare(request,attempt,timeout=min(self.timeout,120),stopping=self.worker.stop.is_set)
            attempt.check()
            if not self.authorize(attempt.task):raise PermissionError('Scope withdrawn during admission')
            if str(self.files(attempt.task['project']).root)!=payload['_root']:raise PermissionError('Workspace binding changed during admission')
            for target in payload['targets']:files.verify(target['path'],target['expected_sha256'])
            for dep in attempt.task['dependencies']:files.verify(dep['path'],dep['sha256'])
            attempt.begin_effect({'phase':'local_submit_uncertain','request_id':request})
            receipt=self.transport.submit(request,packet)
            if not isinstance(receipt,dict) or receipt.get('request_id')!=request or receipt.get('accepted') is not True:
                raise ValueError('Local submission not confirmed')
            attempt.checkpoint({'phase':'local_accepted','request_id':request})
            from local_progress import ProgressGuard
            progress=ProgressGuard();last_progress=None
            deadline=time.monotonic()+self.timeout
            while True:
                attempt.check()
                if self.worker.stop.is_set():raise RuntimeError('Local worker stopping')
                if not self.authorize(attempt.task):raise PermissionError('Scope withdrawn')
                observed=self._observation(request);status=observed['status']
                reason=progress.observe(observed);evidence=progress.evidence()
                if reason or evidence!=last_progress:
                    attempt.checkpoint({'phase':'local_progress_review' if reason else 'local_running','request_id':request,**evidence,**({'reason':reason} if reason else {})})
                    last_progress=evidence
                if reason:raise RuntimeError('Local progress requires review: '+reason)
                if status=='completed':break
                if status in ('failed','canceled'):raise RuntimeError('Local provider did not complete')
                if time.monotonic()>=deadline:raise TimeoutError('Local handoff deadline')
                attempt.cancelled.wait(0.25)
            artifacts=self._evidence(attempt.task,files)
            return {'request_id':request,'provider_status':'completed','verification':'exact_target_hashes',
                    'unrelated_files_verified':False,'tests_run':False},artifacts
        except BaseException:
            # Cancellation is requested, not asserted to have stopped resident compute.
            try:self.transport.cancel(request)
            except Exception:pass
            raise

    def reconcile(self, project, task, version):
        """Explicitly accept verified existing effects; never resubmit after uncertainty."""
        value=self.ledger.get(project,task)
        if value['kind']!='local_exact_edit' or value['status']!='needs_review':
            raise ValueError('Only uncertain local handoffs can be reconciled')
        if not self.authorize(value):raise PermissionError('Scope withdrawn')
        if self._status(task)!='completed':raise ValueError('Provider completion not established')
        artifacts=self._evidence(value,self.files(project))
        return self.ledger.reconcile(project,task,version,{'request_id':task,'provider_status':'completed',
            'verification':'exact_target_hashes','reexecuted':False,'tests_run':False,
            'unrelated_files_verified':False},artifacts)

    def close(self):
        self.worker.close()
