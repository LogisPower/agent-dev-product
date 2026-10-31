"""Original Logis integration. Explicit project resolver; no inferred OS grants."""
import threading
from pathlib import Path
from durable_tasks import Ledger
from project_files import ProjectFiles
from task_worker import Worker, FILE_HANDLERS


class Foundation:
    def __init__(self, state_path, resolve_project, authorize=lambda task: True, docker_mapping=None):
        self.ledger = Ledger(state_path)
        self.resolve_project = resolve_project
        self.mapping = docker_mapping or {}
        self.worker = Worker(self.ledger, FILE_HANDLERS, self.files, authorize)

    def files(self, project):
        # Resolver must recheck project existence/archive/grants on every operation.
        root = Path(self.resolve_project(project))
        return ProjectFiles(root, self.mapping.get(project))

    def query(self, project, action='status', **args):
        files = self.files(project)
        if action == 'status':
            page=self.ledger.list(project, int(args.get('after', 0)))
            for task in page['tasks']:
                task.pop('token',None)
                task['payload'].pop('_principal',None)
            return {**page,
                    'worker': self.worker.status, 'worker_error': self.worker.error_type,
                    'inference': 'Single shared model slot; background status requires no inference.',
                    'supported_jobs': ['file_read', 'file_write'], 'autonomous_coding': False}
        if action == 'task':
            value = self.ledger.get(project, args['task'])
            value.pop('token', None)
            value['payload'].pop('_principal',None)
            return value
        if action == 'list':
            return files.listing(args.get('directory', ''), cursor=args.get('cursor'))
        if action == 'read':
            return files.read(args['path'], offset=int(args.get('offset', 0)), expected_sha256=args.get('sha256'))
        if action == 'search':
            return files.search(args['query'], directory=args.get('directory', ''), content=args.get('content') in (True, 'true'), cursor=args.get('cursor'), limit=100)
        if action == 'effect':
            task = self.ledger.get(project, args['task'])
            return files.workspace.inspect(task['id'])
        raise ValueError('Unknown foundation query')

    def command(self, project, action, body, principal=None):
        files = self.files(project)
        if action in ('submit', 'write_verify'):
            if set(body) - {'kind', 'payload', 'key', 'dependencies'}:
                raise ValueError('Unexpected task fields')
            kind, payload = body['kind'], dict(body['payload'])
            if action == 'write_verify' and kind != 'file_write':
                raise ValueError('Verified-write workflows require a file_write task')
            if kind not in FILE_HANDLERS:
                raise ValueError('Only registered bounded file jobs are currently enabled')
            fields = {'path', 'content', 'expected_sha256'} if kind == 'file_write' else {'path', 'offset', 'limit', 'expected_sha256'}
            if set(payload) - fields:
                raise ValueError('Unexpected file task fields')
            payload['path'] = files.relative(payload['path'])
            if kind == 'file_write':
                if not isinstance(payload.get('content'), str) or len(payload['content'].encode()) > 131072:
                    raise ValueError('Bounded UTF-8 text required')
                if payload.get('expected_sha256') is not None:
                    import re
                    if not re.fullmatch('[a-f0-9]{64}', payload['expected_sha256']):
                        raise ValueError('Invalid expected file version')
            if kind == 'file_read':
                offset, limit = payload.get('offset', 0), payload.get('limit', 16384)
                if type(offset) is not int or not 0 <= offset <= 131072 or type(limit) is not int or not 1 <= limit <= 32768:
                    raise ValueError('Invalid bounded read page')
                expected = payload.get('expected_sha256')
                if expected is not None:
                    import re
                    if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
                        raise ValueError('Invalid expected file version')
                if offset and not expected:
                    raise ValueError('Continuation reads require expected_sha256')
            if principal is not None:payload['_principal']=principal
            if action == 'write_verify':
                result = self.ledger.submit_verified_write(project, body['key'], payload, body.get('dependencies', []))
                for task in result.values():
                    task.pop('token', None)
                    task['payload'].pop('_principal', None)
                return result
            return self.ledger.submit(project, body['key'], kind, payload,
                                      outputs=[payload['path']] if kind == 'file_write' else [],
                                      dependencies=body.get('dependencies', []), approval=kind == 'file_write')
        if action == 'approve':
            task = self.ledger.get(project, body['task'])
            if task['kind'] == 'file_write':
                # App-owned journal provisioning is explicit at approved mutation time.
                journal = files.root / '.logis'
                journal.mkdir(exist_ok=True)
                if journal.is_symlink() or journal.is_junction():
                    raise ValueError('Linked recovery directory rejected')
            return self.ledger.approve(project, task['id'], body['version'])
        if action == 'cancel':
            return self.ledger.cancel(project, body['task'])
        if action == 'reconcile':
            import hashlib
            task=self.ledger.get(project,body['task'])
            if task['kind']!='file_write':raise ValueError('Only verified file-write recovery is supported')
            disk=files.workspace.inspect(task['id'])
            expected=hashlib.sha256(task['payload']['content'].encode()).hexdigest()
            if disk['state']!='verified_effect_observed' or disk['receipt']['path']!=task['payload']['path'] or disk['receipt']['new_hash']!=expected:
                raise ValueError('Effect is not fully verified; no replay or restore performed')
            artifact=files.verify(task['payload']['path'],expected)
            return self.ledger.reconcile(project,task['id'],body['version'],{'receipt':disk['receipt'],'reconciled':True,'reexecuted':False},[artifact])
        raise ValueError('Unknown foundation command')

    def start(self):
        self.worker.start()

    def close(self):
        self.worker.close()
