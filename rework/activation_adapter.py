"""Opt-in app factory. No project/grant creation, listener, model setup or live defaults.

The caller supplies an existing isolated canonical DSN, scoped credentials and a
read-only approval loader. Merely constructing Binding is not authorization.
"""
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Binding:
    project: str
    root: Path
    container_root: str
    state_directory: Path

    def __post_init__(self):
        if not isinstance(self.project, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.project):
            raise ValueError('Explicit canonical project ID required')
        root, state = Path(self.root), Path(self.state_directory)
        for path in (root, state):
            if not path.is_absolute() or '..' in path.parts or path == Path(path.anchor):
                raise ValueError('Explicit absolute non-volume paths required')
        if state.is_relative_to(root) or root.is_relative_to(state):
            raise ValueError('Private runtime state must be separate from project files')
        docker = self.container_root
        if not isinstance(docker, str) or not docker.startswith('/workspace/') or any(p in ('', '.', '..') for p in docker[1:].split('/')):
            raise ValueError('Exact existing /workspace child mapping required')
        if str(PurePosixPath(docker)) != docker:
            raise ValueError('Canonical container path required')
        object.__setattr__(self, 'root', root)
        object.__setattr__(self, 'state_directory', state)

    def expected_approval(self):
        """Describe the required record; never install or persist it."""
        return {'schema_version': 1, 'project': self.project, 'root': str(self.root),
                'container_root': self.container_root, 'state_directory': str(self.state_directory),
                'operations': ['read', 'create', 'edit', 'move']}

    def check_approval(self, approval_reader):
        try:
            value = approval_reader()
            if type(value) is not dict or json.dumps(value, sort_keys=True) != json.dumps(self.expected_approval(), sort_keys=True):
                raise ValueError('Binding differs')
        except (OSError, ValueError, TypeError):
            raise PermissionError('Exact project binding approval missing or changed') from None

    def check_paths(self):
        # Provisioning is a separate approved action, never a side effect here.
        for root in (self.root, self.state_directory):
            for path in (root, *root.parents):
                if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                    raise PermissionError('Linked activation paths are not accepted')
            if not root.is_dir():
                raise ValueError('Project and private state directories must already exist')


def _existing_project(dsn, project):
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row,
                         options='-c default_transaction_read_only=on') as connection:
        directory = connection.execute('SHOW data_directory').fetchone()['data_directory']
        if '/rework/postgres-restore-' not in directory.replace('\\', '/').lower():
            raise RuntimeError('Activation adapter refuses non-isolated database')
        row = connection.execute('SELECT id,archived FROM logis_candidate.projects WHERE id=%s', (project,)).fetchone()
        if not row or row['archived']:
            raise PermissionError('Selected canonical project is missing or archived')


def create_activation_app(binding, dsn, credentials, approval_reader, *, start_workers=False,
                          scope_refresh=None, request_chat=None, request_build=None,
                          context_counter=None, device_store=None, local_transport=None, local_planner=None):
    """Construct the original UI + Foundation app only after exact existing approval.

    A successful call initializes only private ledger state. It does not listen,
    start workers by default, provision folders, create canonical rows, write
    approval files, widen credential scopes, or change existing provider settings.
    """
    if not isinstance(binding, Binding) or not callable(approval_reader):
        raise ValueError('Explicit binding and read-only approval loader required')
    if type(start_workers) is not bool:
        raise ValueError('Worker start must be explicit')
    if start_workers and not (callable(request_chat) and callable(request_build)):
        raise ValueError('Supply existing provider adapters before starting workers')
    if local_transport is not None and (getattr(local_transport,'project',None)!=binding.project or getattr(local_transport,'cwd',None)!=binding.container_root):
        raise ValueError('Local transport must already match this exact project and container root')
    if local_planner is not None and (local_transport is None or not callable(local_planner)):
        raise ValueError('Planning requires an explicit existing text-only provider and bound local transport')

    def resolve(project):
        if project != binding.project:
            raise PermissionError('Project is outside the activation binding')
        binding.check_approval(approval_reader)
        binding.check_paths()
        _existing_project(dsn, project)
        return binding.root

    resolve(binding.project)
    if not credentials or not any(binding.project in value.get('projects', []) for _, value in credentials.items()):
        raise PermissionError('An existing credential must already include this project')
    if device_store is not None:
        device_store = Path(device_store)
        if not device_store.is_absolute() or not device_store.is_file() or device_store.is_relative_to(binding.root):
            raise ValueError('Use an existing device store outside project files')
        for path in (device_store, *device_store.parents):
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise PermissionError('Linked device store rejected')

    def scoped(base):
        value = copy.copy(scope_refresh(base) if scope_refresh else base)
        try:
            resolve(binding.project)
            permitted = binding.project in value.get('projects', [])
        except (PermissionError, ValueError, OSError):
            permitted = False
        value['projects'] = [binding.project] if permitted else []
        value['write'] = bool(value.get('write')) and permitted
        return value

    def files(project, permissions, write=False):
        if project != binding.project or project not in permissions.get('projects', []):
            raise PermissionError('Project not authorized')
        current = getattr(permissions, 'current_summary_scope', None)
        fresh = scoped(current() if callable(current) else permissions)
        if project not in fresh['projects'] or (write and not (permissions.get('write') and fresh.get('write'))):
            raise PermissionError('Project scope or write permission withdrawn')
        from project_files import ProjectFiles
        return ProjectFiles(resolve(project), binding.container_root)

    def authorize(task):
        try:
            resolve(task['project'])
            return True
        except (PermissionError, ValueError, OSError):
            return False

    from foundation_runtime import Foundation
    from candidate_api import create_app
    ledger = binding.state_directory/'tasks.sqlite'
    local_ledger = binding.state_directory/'local-work.sqlite'
    marker = binding.state_directory/'binding-state.json'
    for path in (marker, *(Path(str(base)+suffix) for base in (ledger,local_ledger) for suffix in ('', '-wal', '-shm', '-journal'))):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise PermissionError('Linked private runtime state rejected')
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise PermissionError('Private runtime state must be an unshared regular file')
    identity = {'project': binding.project, 'root': str(binding.root),
                'container_root': binding.container_root, 'purpose': 'runtime_identity_only_not_authorization'}
    if marker.exists():
        if json.loads(marker.read_text(encoding='utf-8')) != identity:
            raise ValueError('Private state belongs to another binding; explicit migration required')
    else:
        if any(Path(str(base)+suffix).exists() for base in (ledger,local_ledger) for suffix in ('', '-wal', '-shm', '-journal')):
            raise ValueError('Existing ledger has no binding record; explicit migration required')
        with marker.open('xb') as handle:
            handle.write(json.dumps(identity, sort_keys=True).encode('utf-8'))
            handle.flush();os.fsync(handle.fileno())
    foundation = Foundation(ledger, resolve, authorize,
                            {binding.project: binding.container_root})
    local_work=None
    if local_transport is not None:
        from local_work_loop import LocalWorkLoop
        local_work=LocalWorkLoop(local_ledger,resolve,authorize,local_transport)
        if local_planner is not None:
            from local_planner import LocalPlanner
            LocalPlanner(local_work,local_planner)
    app = create_app(dsn, credentials, foundation=foundation, original_ui=True,
                     run_worker=False, background_chat=start_workers,
                     foundation_background=start_workers, scope_refresh=scoped,
                     request_chat=request_chat, request_build=request_build,
                     context_counter=context_counter, device_store=device_store,local_work=local_work)
    app.state.project_files = files
    app.state.activation = {'project': binding.project, 'workers_enabled': start_workers,
                            'local_work_enabled':local_work is not None,'local_worker_started':False,
                            'project_created': False, 'grant_created': False}
    return app
