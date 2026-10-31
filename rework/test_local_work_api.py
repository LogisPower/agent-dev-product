import os,tempfile,unittest,uuid
from pathlib import Path
import psycopg
from fastapi.testclient import TestClient
from candidate_api import create_app
from local_work_loop import LocalWorkLoop,digest
from test_local_work_loop import Provider


class LocalWorkApiTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['LOGIS_DISPATCH_TEST_DSN'];self.project='local-ui-'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:c.execute('INSERT INTO logis_candidate.projects(id,name) VALUES(%s,%s)',(self.project,'Synthetic local UI'))
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'files';self.root.mkdir()
        (self.root/'a.txt').write_bytes(b'before')
        self.provider=Provider(self.root)
        def resolve(project):
            if project!=self.project:raise PermissionError('Project denied')
            return self.root
        self.loop=LocalWorkLoop(self.root.parent/'private.sqlite',resolve,lambda task:task['project']==self.project,self.provider,timeout=1)
        self.credentials={'owner':{'projects':[self.project],'write':True},'reader':{'projects':[self.project],'write':False},'outsider':{'projects':['other'],'write':True}}
        self.app=create_app(self.dsn,self.credentials,original_ui=True,local_work=self.loop)
        self.client=TestClient(self.app);self.headers={'Authorization':'Bearer owner'}
        self.base=f'/api/projects/{self.project}/local-work'
        self.body={'key':'ui-edit','edits':[{'path':'a.txt','expected_sha256':digest('before'),'old':'before','new':'after'}]}
    def tearDown(self):self.client.close();self.loop.close();self.temp.cleanup()
    def submit(self):
        response=self.client.post(self.base+'/submit',headers=self.headers,json=self.body)
        self.assertEqual(response.status_code,200,response.text);return response.json()
    def approve(self,task):return self.client.post(self.base+'/approve',headers=self.headers,json={'task':task['id'],'version':task['version']})
    def test_original_ui_prepare_approve_execute_and_redacted_status(self):
        with self.client:
            shell=self.client.get('/logis');self.assertIn('/logis-assets/local-work.js',shell.text)
            self.assertEqual(self.client.get('/logis-assets/local-work.js').status_code,200)
            self.assertIsNone(self.loop.worker.thread)
            page=self.client.get(self.base+'?action=prepare&path=a.txt',headers=self.headers).json()
            self.assertEqual(page['content'],'before');self.assertEqual(page['sha256'],digest('before'))
            task=self.submit();self.assertEqual(task['status'],'approval');self.assertFalse(self.loop.worker.once())
            self.assertEqual(self.approve(task).status_code,200)
            self.loop.worker.once();self.assertEqual((self.root/'a.txt').read_bytes(),b'after')
            state=self.client.get(self.base,headers=self.headers)
            self.assertEqual(state.json()['tasks'][0]['status'],'completed')
            for hidden in ('_principal','_submission','_root','private.sqlite','"token"'):self.assertNotIn(hidden,state.text)
            self.assertEqual(self.submit()['id'],task['id']);self.assertEqual(len(self.provider.calls),1)
    def test_scope_and_input_boundaries(self):
        self.assertEqual(self.client.get(self.base).status_code,401)
        self.assertEqual(self.client.get(self.base,headers={'Authorization':'Bearer outsider'}).status_code,404)
        self.assertEqual(self.client.post(self.base+'/submit',json=self.body,headers={'Authorization':'Bearer reader'}).status_code,403)
        self.assertEqual(self.client.post(self.base+'/submit',json={**self.body,'principal':'fake'},headers=self.headers).status_code,422)
        self.assertEqual(self.client.get(self.base+'?action=prepare&path=../private.sqlite',headers=self.headers).status_code,409)
        self.assertEqual(self.client.get(self.base+'?action=prepare&path=missing.txt',headers=self.headers).json()['status'],'missing')
        (self.root/'large.txt').write_bytes(b'x'*32769)
        self.assertEqual(self.client.get(self.base+'?action=prepare&path=large.txt',headers=self.headers).status_code,409)
        self.assertEqual(self.client.post(self.base+'/submit',json={**self.body,'dependencies':[{'task':'a'*32,'path':'a.txt'}]},headers=self.headers).status_code,409)
        self.assertEqual(self.provider.calls,[])
    def test_revoked_identity_blocks_previously_approved_local_job(self):
        task=self.submit();self.assertEqual(self.approve(task).status_code,200)
        self.credentials['owner']['write']=False;self.loop.worker.once()
        self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.loop.ledger.get(self.project,task['id'])['status'],'failed')
    def test_archive_blocks_submission_and_approved_dispatch(self):
        task=self.submit();self.assertEqual(self.approve(task).status_code,200)
        with psycopg.connect(self.dsn) as c:c.execute('UPDATE logis_candidate.projects SET archived=true WHERE id=%s',(self.project,))
        self.assertEqual(self.client.get(self.base,headers=self.headers).status_code,404)
        self.loop.worker.once();self.assertEqual(self.provider.calls,[])
    def test_other_canonical_file_effect_blocks_local_dispatch(self):
        task=self.submit();self.approve(task)
        with psycopg.connect(self.dsn) as connection:
            connection.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(self.project,))
            self.loop.worker.once()
        self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.loop.ledger.get(self.project,task['id'])['status'],'failed')
    def test_reconcile_checks_existing_effect_without_resubmission(self):
        task=self.submit();self.approve(task);self.provider.uncertain=True;self.loop.worker.once()
        pending=self.client.get(self.base,headers=self.headers).json()['tasks'][0]
        self.assertEqual(pending['status'],'needs_review')
        result=self.client.post(self.base+'/reconcile',headers=self.headers,json={'task':task['id'],'version':pending['version']})
        self.assertEqual(result.status_code,200,result.text);self.assertFalse(result.json()['result']['reexecuted'])
        self.assertEqual(len(self.provider.calls),1)

    def test_plan_endpoint_is_atomic_scoped_and_never_auto_approves(self):
        (self.root/'b.txt').write_bytes(b'second')
        body={'key':'plan','title':'Two changes','steps':[{'name':'first','edit':self.body['edits'][0],'after':[]},
            {'name':'second','edit':{'path':'b.txt','expected_sha256':digest('second'),'old':'second','new':'done'},'after':['first']}]}
        self.assertEqual(self.client.post(self.base+'/plan',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
        response=self.client.post(self.base+'/plan',headers=self.headers,json=body)
        self.assertEqual(response.status_code,200,response.text);plan=response.json()
        self.assertTrue(plan['approval_required']);self.assertFalse(plan['started'])
        self.assertEqual([t['status'] for t in plan['tasks']],['approval','approval'])
        self.assertEqual(plan['tasks'][1]['plan']['after'],['first'])
        self.assertNotIn('contract',response.text);self.assertNotIn('_principal',response.text)
        self.assertFalse(self.loop.worker.once());self.assertEqual(self.provider.calls,[])
        replay=self.client.post(self.base+'/plan',headers=self.headers,json=body).json()
        self.assertEqual([t['id'] for t in replay['tasks']],[t['id'] for t in plan['tasks']])

    def test_planning_context_is_readonly_scoped_and_tracks_current_evidence(self):
        task=self.submit();self.approve(task);self.loop.worker.once()
        path=self.base+'?action=context&path=a.txt'
        self.assertEqual(self.client.get(path,headers={'Authorization':'Bearer outsider'}).status_code,404)
        response=self.client.get(path,headers={'Authorization':'Bearer reader'})
        self.assertEqual(response.status_code,200,response.text)
        context=response.json();self.assertTrue(context['read_only'])
        self.assertTrue(context['tasks'][0]['targets'][0]['current_matches_result'])
        self.assertNotIn('_principal',response.text);self.assertNotIn('private.sqlite',response.text)
        self.assertEqual(len(self.provider.calls),1)

    def test_goal_proposal_api_requires_opt_in_scope_and_separate_approval(self):
        import json
        from local_planner import LocalPlanner
        path=f'/api/projects/{self.project}/local-planning'
        body={'key':'goal','goal':'Change before to after','paths':['a.txt']}
        self.assertEqual(self.client.post(path+'/propose',headers=self.headers,json=body).status_code,409)
        calls=[]
        def provider(messages,**kwargs):
            calls.append(messages);return json.dumps({'title':'Change','steps':[{'name':'a','path':'a.txt','old':'before','new':'after','after':[]}]})
        LocalPlanner(self.loop,provider)
        self.assertEqual(self.client.post(path+'/propose',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
        response=self.client.post(path+'/propose',headers=self.headers,json=body);self.assertEqual(response.status_code,200,response.text)
        task=response.json();self.assertNotIn('content',response.text);self.assertEqual(task['planning']['paths'],['a.txt'])
        self.loop.worker.once();state=self.loop.ledger.get(self.project,task['id'])
        accepted=self.client.post(path+'/accept',headers=self.headers,json={'task':task['id'],'version':state['version']})
        self.assertEqual(accepted.status_code,200,accepted.text)
        self.assertEqual(accepted.json()['tasks'][0]['status'],'approval')
        self.assertEqual((self.root/'a.txt').read_bytes(),b'before');self.assertEqual(self.provider.calls,[])
        self.assertTrue(self.client.get(self.base,headers=self.headers).json()['planning_enabled'])
    def test_analysis_is_scoped_readonly_and_not_automatically_accepted(self):
        import json
        from local_planner import LocalPlanner
        LocalPlanner(self.loop,lambda *a,**k:json.dumps({'summary':'hint','quotes':[]}))
        path=f'/api/projects/{self.project}/local-planning';body={'key':'analysis','goal':'Explain','path':'a.txt'}
        self.assertEqual(self.client.post(path+'/analyze',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
        response=self.client.post(path+'/analyze',headers=self.headers,json=body)
        self.assertEqual(response.status_code,200,response.text);task=response.json()
        self.assertNotIn('_root',response.text);self.assertNotIn('_principal',response.text)
        self.loop.worker.once();done=self.loop.ledger.get(self.project,task['id'])
        self.assertEqual(done['status'],'completed');self.assertTrue(done['result']['read_only'])
        self.assertEqual((self.root/'a.txt').read_bytes(),b'before');self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.client.post(path+'/accept',headers=self.headers,json={'task':task['id'],'version':done['version']}).status_code,409)
    def test_discovery_scoped_without_model_and_explicit_transition(self):
        path=f'/api/projects/{self.project}/local-planning'
        body={'key':'find','query':'before'}
        self.assertEqual(self.client.post(path+'/discover',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
        self.assertEqual(self.client.post(path+'/discover',headers=self.headers,json={**body,'principal':'fake'}).status_code,422)
        response=self.client.post(path+'/discover',headers=self.headers,json=body);self.assertEqual(response.status_code,200,response.text)
        task=response.json();self.assertEqual(task['kind'],'local_discovery');self.assertNotIn('_root',response.text);self.loop.worker.once()
        state=self.loop.ledger.get(self.project,task['id']);self.assertEqual(state['status'],'completed')
        transition={'task':task['id'],'version':state['version'],'goal':'Change','paths':['a.txt']}
        self.assertEqual(self.client.post(path+'/from-discovery',headers=self.headers,json=transition).status_code,409)
        from local_planner import LocalPlanner
        LocalPlanner(self.loop,lambda *a,**kw:'unused')
        self.assertEqual(self.client.post(path+'/from-discovery',headers=self.headers,json={**transition,'allow_completed':'yes'}).status_code,422)
        result=self.client.post(path+'/from-discovery',headers=self.headers,json=transition);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['planning']['discovery'],task['id']);self.assertEqual(self.provider.calls,[])
    def test_new_file_authoring_api_review_writer_and_scope(self):
        import json
        from foundation_runtime import Foundation
        from local_planner import LocalPlanner
        foundation=Foundation(self.root.parent/'foundation.sqlite',lambda _:self.root,lambda task:task['project']==self.project)
        self.app.state.foundation=foundation
        LocalPlanner(self.loop,lambda *a,**kw:json.dumps({'path':'new.py','content':'VALUE = 1\n'}))
        path=f'/api/projects/{self.project}/local-planning'
        body={'key':'new','goal':'Add VALUE','path':'new.py','context_paths':['a.txt']}
        try:
            self.assertEqual(self.client.post(path+'/author',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
            response=self.client.post(path+'/author',headers=self.headers,json=body);self.assertEqual(response.status_code,200,response.text)
            task=response.json();self.assertEqual(task['authoring']['path'],'new.py');self.assertNotIn('_principal',response.text)
            self.loop.worker.once();state=self.loop.ledger.get(self.project,task['id']);decision={'task':task['id'],'version':state['version']}
            self.assertEqual(self.client.post(path+'/accept-author',headers={'Authorization':'Bearer reader'},json=decision).status_code,403)
            accepted=self.client.post(path+'/accept-author',headers=self.headers,json=decision);self.assertEqual(accepted.status_code,200,accepted.text)
            self.assertEqual(accepted.json()['write']['status'],'approval');self.assertFalse((self.root/'new.py').exists());self.assertEqual(self.provider.calls,[])
            workflow=self.client.post(path+'/author-workflow',headers={'Authorization':'Bearer reader'},json=decision)
            self.assertEqual(workflow.status_code,200,workflow.text);self.assertEqual(len(workflow.json()['tasks']),2);self.assertNotIn('_principal',workflow.text)
        finally:foundation.close()
    def test_mixed_plan_api_scoped_review_and_replay(self):
        import json
        from foundation_runtime import Foundation
        from local_planner import LocalPlanner
        foundation=Foundation(self.root.parent/'foundation.sqlite',lambda _:self.root,lambda task:task['project']==self.project);self.app.state.foundation=foundation
        LocalPlanner(self.loop,lambda *a,**kw:json.dumps({'path':'new.py','content':'VALUE = 1\n'}))
        path=f'/api/projects/{self.project}/local-planning'
        try:
            response=self.client.post(path+'/author',headers=self.headers,json={'key':'new','goal':'Add VALUE','path':'new.py'});self.assertEqual(response.status_code,200,response.text)
            self.loop.worker.once();task=self.loop.ledger.get(self.project,response.json()['id']);body={'key':'mixed','title':'Mixed','selections':[{'task':task['id'],'version':task['version']}]}
            self.assertEqual(self.client.post(path+'/mixed',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
            result=self.client.post(path+'/mixed',headers=self.headers,json=body);self.assertEqual(result.status_code,200,result.text);self.assertEqual(len(result.json()['tasks']),2)
            self.assertEqual(result.json()['tasks'][0]['status'],'approval');self.assertFalse((self.root/'new.py').exists())
            self.assertEqual(self.client.post(path+'/mixed',headers=self.headers,json=body).json()['id'],result.json()['id'])
            status=self.client.get(path+'/mixed',headers={'Authorization':'Bearer reader'});self.assertEqual(status.status_code,200,status.text)
            self.assertNotIn('_principal',status.text);self.assertNotIn('"root"',status.text);self.assertTrue(status.json()['read_only'])
        finally:foundation.close()
    def test_proposal_admission_lock_is_shared_by_acceptance_routes(self):
        path=f'/api/projects/{self.project}/local-planning'
        with psycopg.connect(self.dsn) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('logis-proposal-admission:'+self.project,))
            for action in ('accept','accept-author'):
                response=self.client.post(path+'/'+action,headers=self.headers,json={'task':'a'*32,'version':1})
                self.assertEqual(response.status_code,409,response.text);self.assertIn('admission is active',response.text)
            response=self.client.post(path+'/mixed',headers=self.headers,json={'key':'busy','title':'Busy','selections':[{'task':'a'*32,'version':1}]})
            self.assertEqual(response.status_code,409,response.text);self.assertIn('admission is active',response.text)
    def test_saved_project_verification_scope_metadata_and_no_model(self):
        path=f'/api/projects/{self.project}/local-planning'
        (self.root/'module.ts').write_text('export const value: number = 1;')
        body={'key':'verify','paths':['module.ts']}
        self.assertEqual(self.client.post(path+'/verify',headers={'Authorization':'Bearer reader'},json=body).status_code,403)
        self.assertEqual(self.client.post(path+'/verify',headers=self.headers,json={**body,'command':'npm test'}).status_code,422)
        response=self.client.post(path+'/verify',headers=self.headers,json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['verification']['paths'],['module.ts']);self.assertNotIn('_principal',response.text)
        self.loop.worker.once();state=self.loop.ledger.get(self.project,response.json()['id']);self.assertEqual(state['status'],'completed',state);self.assertTrue(state['result']['passed'])
        self.assertEqual(self.provider.calls,[]);self.assertEqual(self.client.post(path+'/verify',headers=self.headers,json=body).json()['id'],state['id'])
