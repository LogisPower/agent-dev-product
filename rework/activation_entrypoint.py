"""Explicit trusted launch composition. No installation, credentials or grants created.

CLI --check is read-only. A trusted Python host supplies existing provider callbacks
and calls serve() only after separate activation authorization. JSON cannot name
Python modules, commands, models or provider endpoints.
"""
import argparse,json,sys
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from activation_adapter import Binding,_existing_project,create_activation_app
from workspace_files import Workspace


def unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('Duplicate configuration field')
        value[key]=item
    return value

class ProtectedJSON:
    def __init__(self,path,excluded=None):
        self.path=Path(path)
        if not self.path.is_absolute() or '..' in self.path.parts:raise ValueError('Explicit absolute configuration file required')
        if excluded is not None and self.path.is_relative_to(excluded):raise PermissionError('Configuration must remain outside model-writable project files')
    def read(self):
        # Reuse pinned Windows ancestor/file handles and hard-link rejection.
        result=Workspace(self.path.parent).read(self.path.name)
        if result['bytes']>65536:raise ValueError('Protected JSON exceeds bound')
        value=json.loads(result['content'],object_pairs_hook=unique)
        if type(value) is not dict:raise ValueError('Protected JSON object required')
        return value

class FileCredentials(Mapping):
    def __init__(self,reader):self.reader=reader
    def snapshot(self):
        value=self.reader.read()
        if not value or len(value)>64:raise ValueError('Existing bounded credential map required')
        for token,scope in value.items():
            if not isinstance(token,str) or not 1<=len(token)<=512 or type(scope) is not dict or set(scope)!={'projects','write'}:raise ValueError('Explicit credential scopes required')
            if type(scope['write']) is not bool or not isinstance(scope['projects'],list) or len(scope['projects'])>100 or any(not isinstance(p,str) or not 1<=len(p)<=100 for p in scope['projects']):raise ValueError('Invalid credential scope')
        return value
    def __getitem__(self,key):return self.snapshot()[key]
    def __iter__(self):return iter(self.snapshot())
    def __len__(self):return len(self.snapshot())
    def items(self):return self.snapshot().items()

@dataclass(frozen=True)
class RuntimeAdapters:
    request_chat:object=None
    request_build:object=None
    context_counter:object=None
    local_transport:object=None
    local_planner:object=None


def load_configuration(path):
    config=ProtectedJSON(path).read()
    if set(config)!={'binding','database_file','credentials_file','approval_file','listener','workers'}:raise ValueError('Exact launch configuration fields required')
    value=config['binding']
    if type(value) is not dict or set(value)!={'project','root','container_root','state_directory'}:raise ValueError('Exact binding required')
    binding=Binding(**value)
    ProtectedJSON(path,binding.root)
    readers={name:ProtectedJSON(config[name],binding.root) for name in ('database_file','credentials_file','approval_file')}
    if len({reader.path for reader in readers.values()}|{Path(path)})!=4:raise ValueError('Separate configuration, database, credentials and approval files required')
    listener=config['listener']
    if type(listener) is not dict or set(listener)!={'host','port'} or listener['host']!='127.0.0.1' or type(listener['port']) is not int or not 1024<=listener['port']<=65535:raise ValueError('Explicit loopback listener and unprivileged port required')
    workers=config['workers']
    if type(workers) is not dict or set(workers)!={'foundation','chat','local'} or any(type(v) is not bool for v in workers.values()):raise ValueError('Explicit worker selections required')
    if workers['chat'] and not workers['foundation']:raise ValueError('Existing durable chat startup also requires the Foundation worker')
    database=readers['database_file'].read()
    if set(database)!={'dsn'} or not isinstance(database['dsn'],str) or not 1<=len(database['dsn'])<=4096:raise ValueError('Existing explicit database DSN required')
    return config,binding,database['dsn'],FileCredentials(readers['credentials_file']),readers['approval_file'].read


def check_configuration(path,adapters=None):
    adapters=adapters or RuntimeAdapters()
    config,binding,dsn,credentials,approval=load_configuration(path)
    binding.check_paths();binding.check_approval(approval);_existing_project(dsn,binding.project)
    if not any(binding.project in scope['projects'] for _,scope in credentials.items()):raise PermissionError('Existing credential lacks selected project scope')
    workers=config['workers']
    if workers['chat'] and not (callable(adapters.request_chat) and callable(adapters.request_build)):raise ValueError('Chat worker requires supplied existing chat/build adapters')
    if workers['local'] and (adapters.local_transport is None or not callable(adapters.local_planner)):raise ValueError('Local worker requires supplied existing transport and text planner')
    if adapters.local_transport is not None and (getattr(adapters.local_transport,'project',None)!=binding.project or getattr(adapters.local_transport,'cwd',None)!=binding.container_root):raise ValueError('Transport does not match approved project mapping')
    if adapters.local_planner is not None and (adapters.local_transport is None or not callable(adapters.local_planner)):raise ValueError('Planner requires an existing bound transport')
    marker=binding.state_directory/'binding-state.json'
    identity={'project':binding.project,'root':str(binding.root),'container_root':binding.container_root,'purpose':'runtime_identity_only_not_authorization'}
    if marker.exists():
        if ProtectedJSON(marker,binding.root).read()!=identity:raise ValueError('Private state binding mismatch')
    elif any(Path(str(binding.state_directory/name)+suffix).exists() for name in ('tasks.sqlite','local-work.sqlite') for suffix in ('','-wal','-shm','-journal')):raise ValueError('Unmarked private state requires explicit migration')
    return {'project':binding.project,'root':str(binding.root),'container_root':binding.container_root,'state_directory':str(binding.state_directory),
        'listener':config['listener'],'workers_requested':workers,'read_only_check':True,'local_adapters_supplied':adapters.local_transport is not None,
        'notice':'Configuration checks passed; this is not activation approval, a port reservation, or proof of provider readiness. No listener or worker started.'}


def build_application(path,adapters=None):
    adapters=adapters or RuntimeAdapters();before=ProtectedJSON(path).read();report=check_configuration(path,adapters)
    config,binding,dsn,credentials,approval=load_configuration(path)
    if config!=before:raise ValueError('Launch configuration changed during validation')
    # No dynamic provider imports, token discovery or model configuration here.
    app=create_activation_app(binding,dsn,credentials,approval,start_workers=config['workers']['chat'],
        request_chat=adapters.request_chat,request_build=adapters.request_build,context_counter=adapters.context_counter,
        local_transport=adapters.local_transport,local_planner=adapters.local_planner)
    original=app.router.lifespan_context;workers=dict(config['workers'])
    @asynccontextmanager
    async def managed(application):
        try:
            async with original(application):
                if workers['foundation'] and not workers['chat']:application.state.foundation.start()
                if workers['local']:application.state.local_work.worker.start()
                application.state.activation['managed_workers']=dict(workers)
                application.state.activation['local_worker_started']=workers['local']
                yield
        finally:
            if getattr(application.state,'local_work',None) is not None:application.state.local_work.close()
            if workers['chat']:application.state.durable_dispatch.close()
            application.state.foundation.close()
            application.state.activation['managed_workers']={name:'stop_requested' for name,enabled in workers.items() if enabled}
            local=getattr(application.state,'local_work',None)
            application.state.activation['local_worker_started']=bool(local and local.worker.thread and local.worker.thread.is_alive())
    app.router.lifespan_context=managed
    app.state.launch_report=report
    return app,config['listener']


def serve(path,adapters):
    """Explicit authorized trusted-host entrypoint; never called by --check."""
    app,listener=build_application(path,adapters)
    import uvicorn
    uvicorn.run(app,host=listener['host'],port=listener['port'],workers=1,access_log=False,log_level='warning')


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only Logis launch configuration check; creates no credentials or grants.')
    parser.add_argument('--check',required=True,metavar='ABSOLUTE_CONFIG_JSON');args=parser.parse_args(argv)
    try:print(json.dumps(check_configuration(args.check),indent=2));return 0
    except Exception as error:
        # DSNs and credential material must never reach a CLI traceback or error echo.
        print(json.dumps({'ready':False,'error_type':type(error).__name__,'notice':'Configuration check failed. Review explicit paths, existing approval/scope and supplied adapter requirements.'}));return 1

if __name__=='__main__':raise SystemExit(main())
