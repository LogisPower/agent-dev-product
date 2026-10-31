import io,json,time,unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_activation_adapter as fixture
from activation_entrypoint import ProtectedJSON,RuntimeAdapters,check_configuration,build_application,main
from test_local_work_loop import Provider

class EntrypointTests(unittest.TestCase):
    def setUp(self):
        fixture.ActivationTests.setUp(self)
        self.base=self.root.parent;self.approval_path=self.base/'approval.json';self.credentials_path=self.base/'credentials.json';self.database_path=self.base/'database.json';self.config_path=self.base/'launch.json'
        self.approval_path.write_text(json.dumps(self.approval));self.credentials_path.write_text(json.dumps(self.credentials));self.database_path.write_text(json.dumps({'dsn':self.dsn}))
        self.config={'binding':{'project':self.project,'root':str(self.root),'container_root':self.binding.container_root,'state_directory':str(self.state)},'database_file':str(self.database_path),'credentials_file':str(self.credentials_path),'approval_file':str(self.approval_path),'listener':{'host':'127.0.0.1','port':60199},'workers':{'foundation':False,'chat':False,'local':False}}
        self.save()
    def save(self):self.config_path.write_text(json.dumps(self.config))
    tearDown=fixture.ActivationTests.tearDown
    def test_readonly_check_and_offline_original_ui(self):
        report=check_configuration(self.config_path);self.assertTrue(report['read_only_check']);self.assertEqual(list(self.state.iterdir()),[])
        self.assertNotIn('owner',json.dumps(report));self.assertNotIn(self.dsn,json.dumps(report))
        app,listener=build_application(self.config_path);self.apps.append(app)
        with TestClient(app) as client:
            self.assertIn('/logis-assets/local-work.js',client.get('/logis').text)
            self.assertEqual(client.get(f'/api/projects/{self.project}/foundation',headers=self.headers).status_code,200)
            self.assertIsNone(app.state.foundation.worker.thread)
        self.assertEqual(listener,{'host':'127.0.0.1','port':60199})
    def test_live_file_revocation_and_no_grant_creation(self):
        app,_=build_application(self.config_path);self.apps.append(app)
        with TestClient(app) as client:
            self.credentials_path.write_text(json.dumps({'reader':self.credentials['reader']}))
            self.assertEqual(client.get(f'/api/projects/{self.project}/foundation',headers=self.headers).status_code,401)
            self.credentials_path.write_text(json.dumps(self.credentials));self.approval_path.write_text('{}')
            self.assertIn(client.get(f'/api/projects/{self.project}/foundation',headers=self.headers).status_code,(403,404,409))
        self.assertEqual(self.approval_path.read_text(),'{}')
    def test_explicit_local_lifecycle_executes_only_approved_fixture_edit(self):
        (self.root/'a.txt').write_text('before');provider=Provider(self.root);provider.project=self.project;provider.cwd=self.binding.container_root
        self.config['workers']['local']=True;self.save()
        with self.assertRaises(ValueError):check_configuration(self.config_path)
        self.assertEqual(list(self.state.iterdir()),[])
        adapters=RuntimeAdapters(local_transport=provider,local_planner=lambda *a,**kw:'{}')
        app,_=build_application(self.config_path,adapters);self.apps.append(app)
        from local_work_loop import digest
        with TestClient(app) as client:
            path=f'/api/projects/{self.project}/local-work'
            result=client.post(path+'/submit',headers=self.headers,json={'key':'edit','edits':[{'path':'a.txt','expected_sha256':digest('before'),'old':'before','new':'after'}]});self.assertEqual(result.status_code,200,result.text)
            task=result.json();self.assertEqual(task['status'],'approval');self.assertEqual(provider.calls,[])
            self.assertEqual(client.post(path+'/approve',headers=self.headers,json={'task':task['id'],'version':task['version']}).status_code,200)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if app.state.local_work.ledger.get(self.project,task['id'])['status']=='completed':break
                time.sleep(0.05)
            self.assertEqual((self.root/'a.txt').read_text(),'after');self.assertEqual(provider.calls,[task['id']])
        self.assertFalse(app.state.local_work.worker.thread.is_alive());self.assertFalse(app.state.activation['local_worker_started'])
    def test_paths_schema_and_linked_controls_fail_closed(self):
        self.config['approval_file']=str(self.root/'approval.json');(self.root/'approval.json').write_text(json.dumps(self.approval));self.save()
        with self.assertRaises(PermissionError):check_configuration(self.config_path)
        self.config['approval_file']=str(self.approval_path);self.config['listener']['host']='0.0.0.0';self.save()
        with self.assertRaises(ValueError):check_configuration(self.config_path)
        self.config['listener']['host']='127.0.0.1';self.config['command']='arbitrary';self.save()
        with self.assertRaises(ValueError):check_configuration(self.config_path)
        linked=self.base/'linked.json';linked.hardlink_to(self.approval_path)
        with self.assertRaises(ValueError):ProtectedJSON(linked).read()
    def test_cli_errors_redact_private_details(self):
        output=io.StringIO()
        with patch('activation_entrypoint.check_configuration',side_effect=RuntimeError('secret-dsn-and-token')),redirect_stdout(output):code=main(['--check',str(self.config_path)])
        self.assertEqual(code,1);self.assertNotIn('secret-dsn-and-token',output.getvalue());self.assertIn('RuntimeError',output.getvalue())
    def test_startup_failure_stops_already_started_owned_workers(self):
        provider=Provider(self.root);provider.project=self.project;provider.cwd=self.binding.container_root
        self.config['workers'].update(foundation=True,local=True);self.save()
        app,_=build_application(self.config_path,RuntimeAdapters(local_transport=provider,local_planner=lambda *a,**kw:'{}'));self.apps.append(app)
        with patch.object(app.state.local_work.worker,'start',side_effect=RuntimeError('synthetic startup failure')):
            with self.assertRaises(RuntimeError):
                with TestClient(app):pass
        self.assertFalse(app.state.foundation.worker.thread.is_alive());self.assertEqual(provider.calls,[])
    def test_chat_selection_enables_durable_api_mode(self):
        self.config['workers']['chat']=True;self.save()
        adapters=RuntimeAdapters(request_chat=lambda *a,**kw:'unused',request_build=lambda *a,**kw:'unused')
        with self.assertRaises(ValueError):check_configuration(self.config_path,adapters)
        self.assertEqual(list(self.state.iterdir()),[])
        self.config['workers']['foundation']=True;self.save();app,_=build_application(self.config_path,adapters);self.apps.append(app)
        self.assertTrue(app.state.durable_background);self.assertTrue(app.state.activation['workers_enabled'])
    def test_serve_uses_explicit_loopback_without_reload_or_extra_processes(self):
        from activation_entrypoint import serve
        with patch('uvicorn.run') as run:
            serve(self.config_path,RuntimeAdapters())
            args,kwargs=run.call_args;self.apps.append(args[0]);self.assertEqual(kwargs['host'],'127.0.0.1');self.assertEqual(kwargs['port'],60199)
            self.assertEqual(kwargs['workers'],1);self.assertFalse(kwargs['access_log']);self.assertNotIn('reload',kwargs)
