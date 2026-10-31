"""Activation fixtures use only disposable DB and temporary sibling directories."""
import copy, os, tempfile, unittest, uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from activation_adapter import Binding, create_activation_app
from intent_core import Action
from workspace_facade import execute
from system_summary import bind_scope


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['LOGIS_DISPATCH_TEST_DSN']
        self.project='logis-development'
        with psycopg.connect(self.dsn) as c:
            directory=c.execute('SHOW data_directory').fetchone()[0]
            assert directory.replace('\\','/').endswith('/rework/postgres-restore-synthetic')
            c.execute('INSERT INTO logis_candidate.projects(id,name) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET archived=false',(self.project,'Logis Development'))
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        self.root=base/'project';self.state=base/'private';self.root.mkdir();self.state.mkdir()
        self.binding=Binding(self.project,self.root,'/workspace/logis-harness-next/original-logis',self.state)
        self.approval=self.binding.expected_approval()
        self.credentials={'owner':{'projects':[self.project,'other'],'write':True},'reader':{'projects':[self.project],'write':False},'outsider':{'projects':['other'],'write':True}}
        self.apps=[];self.headers={'Authorization':'Bearer owner'}
    def tearDown(self):
        for app in self.apps:app.state.foundation.close()
        self.temp.cleanup()
    def app(self,**kwargs):
        app=create_activation_app(self.binding,self.dsn,self.credentials,lambda:self.approval,**kwargs)
        self.apps.append(app);return app
    @contextmanager
    def db(self,readonly=True):
        with psycopg.connect(self.dsn,row_factory=dict_row) as c:yield c
    def origin(self):
        run=uuid.uuid4().hex
        with self.db(False) as c:c.execute("INSERT INTO logis_candidate.runs(id,project_id,status,payload) VALUES(%s,%s,'running','{}')",(run,self.project))
        return run
    def test_refuses_missing_approval_scope_project_and_paths_without_provisioning(self):
        self.approval=None
        with self.assertRaises(PermissionError):self.app()
        self.assertEqual(list(self.state.iterdir()),[])
        self.approval=self.binding.expected_approval();self.credentials={}
        with self.assertRaises(PermissionError):self.app()
        self.assertEqual(list(self.state.iterdir()),[])
        self.credentials={'owner':{'projects':[self.project],'write':True}}
        with self.db(False) as c:c.execute('UPDATE logis_candidate.projects SET archived=true WHERE id=%s',(self.project,))
        with self.assertRaises(PermissionError):self.app()
        self.assertEqual(list(self.state.iterdir()),[])
        with self.assertRaises(ValueError):Binding(self.project,self.root,'/workspace/test',self.root/'private')
        missing=Binding(self.project,self.root/'absent','/workspace/test',self.state)
        with self.assertRaises(ValueError):missing.check_paths()
        self.assertFalse(missing.root.exists())
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaises(PermissionError):self.binding.check_paths()
    def test_original_ui_scope_mapping_and_no_background_worker(self):
        before=copy.deepcopy(self.credentials);app=self.app()
        with TestClient(app) as client:
            self.assertEqual(client.get('/logis').status_code,200)
            self.assertEqual([p['id'] for p in client.get('/api/projects',headers=self.headers).json()],[self.project])
            self.assertEqual(client.get('/api/projects',headers={'Authorization':'Bearer outsider'}).json(),[])
            self.assertFalse(app.state.activation['workers_enabled'])
            self.assertIsNone(app.state.foundation.worker.thread)
            self.assertEqual(self.credentials,before)
            (self.root/'sample.txt').write_text('original')
            resolver=app.state.project_files;scope=self.credentials['owner']
            with patch('workspace_facade.workspace',side_effect=AssertionError('legacy fallback')):
                value=execute(self.db,self.project,Action(tool='workspace_read',path=self.binding.container_root+'/sample.txt'),scope,'',files_resolver=resolver)
            self.assertEqual(value['content'],'original')
            from shared_tools import execute as shared_execute
            from tool_catalog import catalog
            with patch('workspace_facade.enabled',return_value=False):
                tools=catalog(app,scope)
                self.assertTrue(tools['workspace_read']['registered'])
                self.assertFalse(tools['setup_checklist']['registered'])
                self.assertFalse(tools['checklist_addon']['registered'])
                result=shared_execute(app,self.db,self.project,Action(tool='workspace_read',path='sample.txt'),scope,'','synthetic')
                self.assertEqual(result['data']['content'],'original')
            for path in ('../private/tasks.sqlite','/workspace/other/sample.txt',str(self.state/'tasks.sqlite')):
                with self.assertRaises(ValueError):resolver(self.project,scope).read(path)
            with self.assertRaises(PermissionError):resolver('other',scope)
            with self.assertRaises(PermissionError):resolver(self.project,self.credentials['reader'],True)
    def test_durable_write_shared_read_edit_and_recovery_use_same_root(self):
        app=self.app();runtime=app.state.foundation
        with TestClient(app) as client:
            prefix=f'/api/projects/{self.project}/foundation'
            response=client.post(prefix+'/write_verify',headers=self.headers,json={'kind':'file_write','key':'synthetic','payload':{'path':'sample.txt','content':'first'}})
            self.assertEqual(response.status_code,200,response.text);pair=response.json();writer=pair['write']
            self.assertFalse(runtime.worker.once());self.assertFalse((self.root/'sample.txt').exists())
            self.assertEqual(client.post(prefix+'/approve',headers=self.headers,json={'task':writer['id'],'version':writer['version']}).status_code,200)
            self.assertTrue(runtime.worker.once());self.assertTrue(runtime.worker.once())
            verified=runtime.ledger.get(self.project,pair['verify']['id'])
            self.assertEqual(verified['status'],'completed')
            run=self.origin();scope=self.credentials['owner'];resolver=app.state.project_files
            action=Action(tool='workspace_edit',path=self.binding.container_root+'/sample.txt',text='second',expected_sha256=verified['result']['sha256'])
            execute(self.db,self.project,action,scope,run,files_resolver=resolver)
            self.assertEqual(resolver(self.project,scope).read('sample.txt')['content'],'second')
            recovery=client.get(f'/api/projects/{self.project}/workspace/effects/{run}',headers=self.headers)
            self.assertEqual(recovery.status_code,200,recovery.text)
            self.assertTrue(recovery.json()['database_effect_recorded'])
            self.assertFalse(recovery.json()['mutations_performed'])
            with self.assertRaises(ValueError):execute(self.db,self.project,action,scope,self.origin(),files_resolver=resolver)
            self.assertEqual((self.root/'sample.txt').read_text(),'second')
    def test_revocation_stops_queued_effect_and_stale_shared_scope(self):
        app=self.app();runtime=app.state.foundation
        with TestClient(app) as client:
            prefix=f'/api/projects/{self.project}/foundation'
            task=client.post(prefix+'/submit',headers=self.headers,json={'kind':'file_write','key':'revoke','payload':{'path':'never.txt','content':'no'}}).json()
            self.assertEqual(client.post(prefix+'/approve',headers=self.headers,json={'task':task['id'],'version':task['version']}).status_code,200)
            stale=bind_scope(dict(self.credentials['owner']),lambda:self.credentials['owner'])
            self.credentials['owner']['write']=False
            with self.assertRaises(PermissionError):app.state.project_files(self.project,stale,True)
            self.approval=None
            runtime.worker.once()
            self.assertFalse((self.root/'never.txt').exists())
            self.assertNotEqual(runtime.ledger.get(self.project,task['id'])['status'],'completed')
            self.assertEqual(client.get('/api/projects',headers=self.headers).json(),[])
            with self.assertRaises(PermissionError):app.state.project_files(self.project,stale)
    def test_private_state_cannot_be_silently_rebound_or_adopted(self):
        app=self.app();app.state.foundation.close()
        marker=(self.state/'binding-state.json').read_bytes()
        other=self.root.parent/'other';other.mkdir()
        changed=Binding(self.project,other,self.binding.container_root,self.state)
        with self.assertRaises(ValueError):create_activation_app(changed,self.dsn,self.credentials,changed.expected_approval)
        self.assertEqual((self.state/'binding-state.json').read_bytes(),marker)
        empty=self.root.parent/'unbound';empty.mkdir();(empty/'tasks.sqlite').write_bytes(b'existing')
        changed=Binding(self.project,self.root,self.binding.container_root,empty)
        with self.assertRaises(ValueError):create_activation_app(changed,self.dsn,self.credentials,changed.expected_approval)
        self.assertFalse((empty/'binding-state.json').exists())
        with self.assertRaises(ValueError):self.app(start_workers=True)

    def test_opt_in_workers_exclude_global_outbox_and_understanding(self):
        with patch('candidate_api.create_app') as factory:
            app=create_activation_app(self.binding,self.dsn,self.credentials,lambda:self.approval,
                start_workers=True,request_chat=lambda:None,request_build=lambda:None)
            args=factory.call_args.kwargs
            try:
                self.assertFalse(args['run_worker'])
                self.assertTrue(args['background_chat']);self.assertTrue(args['foundation_background'])
            finally:args['foundation'].close()

    def test_optional_local_loop_requires_matching_transport_and_stays_stopped(self):
        from test_local_work_loop import Provider
        provider=Provider(self.root)
        with self.assertRaises(ValueError):self.app(local_transport=provider)
        provider.project=self.project;provider.cwd=self.binding.container_root
        with self.assertRaises(ValueError):self.app(local_planner=lambda:None)
        app=self.app(local_transport=provider,local_planner=lambda *args,**kwargs:'{}')
        try:
            with TestClient(app) as client:
                response=client.get(f'/api/projects/{self.project}/local-work',headers=self.headers)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['worker'],'stopped')
                self.assertTrue(response.json()['planning_enabled'])
                self.assertIsNone(app.state.local_work.worker.thread)
                self.assertTrue(app.state.activation['local_work_enabled'])
                self.assertFalse(app.state.activation['local_worker_started'])
        finally:app.state.local_work.close()
