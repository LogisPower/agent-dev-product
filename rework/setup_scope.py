"""Exact persisted setup-health grant; no implicit expansion on project changes."""
import json,hashlib,contextlib
from pathlib import Path
ROOT=Path(r'C:\Users\LOGIS_USER\Documents\LogisWorkspaces')

class ResolvedScope(dict):
    def __init__(self,value,check):
        super().__init__(value);self.setup_health_allowed=check

class ScopeResolver:
    def __init__(self,projects,app_root,project_provider):
        self.projects=tuple(projects);self.root=Path(app_root);self.project_provider=project_provider
    def active(self):
        try:
            current=self.project_provider()
            if len(current)!=len(self.projects) or set(current)!=set(self.projects):return False
            return credentials(list(self.projects),self.root).get('setup_activity_read') is True
        except Exception:return False  # Unknown grant state cannot authorize telemetry.
    def resolve(self,base):
        value=dict(base);value.pop('setup_activity_read',None)
        eligible=bool(value.get('write') and value.get('projects') and set(value['projects']).issubset(self.projects))
        check=lambda:eligible and self.active()
        value['setup_activity_read']=check()
        return ResolvedScope(value,check)

def request_allowed(permissions):
    callback=getattr(permissions,'setup_health_allowed',None)
    return bool(callback()) if callable(callback) else permissions.get('setup_activity_read') is True

def database_projects(dsn):
    import psycopg
    with psycopg.connect(dsn,connect_timeout=2,options='-c default_transaction_read_only=on -c statement_timeout=2000') as c:
        return [row[0] for row in c.execute('SELECT id FROM logis_candidate.projects')]

def device_scope(granted,current):
    # Invoked only after the existing session validity/owner/project checks.
    # Reconcile this newly approved flag dynamically; never retain it after
    # removal of the exact persisted grant. No other permission is added.
    value=dict(granted)
    value['setup_activity_read']=bool(current.get('setup_activity_read') is True and value.get('write') and value.get('projects') and set(value['projects']).issubset(current.get('projects',[])))
    return value

def credentials(projects,app_root):
    value={'projects':projects,'write':True}
    try:
        path=Path(app_root)/'setup-health-access.json'
        if not path.exists():return value
        if path.stat().st_size>16000:raise ValueError('Grant bound')
        grant=json.loads(path.read_text(encoding='utf-8'))
        if set(grant)!={'schema_version','enabled','workspace_root','project_ids'} or grant['schema_version']!=1 or grant['enabled'] is not True or grant['workspace_root']!=str(ROOT):raise ValueError('Grant schema/root')
        ids=grant['project_ids']
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids) or set(ids)!=set(projects):raise ValueError('Grant scope changed; explicit reconciliation needed')
        from workspace_facade import enabled
        if not enabled():raise ValueError('Workspace grant unavailable')
        from workspace_files import WinIO
        io=WinIO()
        with contextlib.ExitStack() as stack:
            for p in reversed([ROOT,*ROOT.parents]):stack.enter_context(io.opened(p,directory=True))
            for project in ids:
                folder=ROOT/hashlib.sha256(project.encode()).hexdigest()
                with io.opened(folder,directory=True),io.opened(folder/'.logis',directory=True):pass
        value['setup_activity_read']=True
    except (OSError,ValueError,TypeError):
        # Existing login/project access stays intact. Unknown setup scope is off.
        return value
    return value
