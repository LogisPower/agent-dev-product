import hashlib,json,tempfile,unittest
from pathlib import Path
from local_work_loop import LocalWorkLoop,digest
from local_work_plan import submit_plan
from test_local_work_loop import Provider


class LocalPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'files';self.root.mkdir()
        for name in ('a','b'):(self.root/(name+'.txt')).write_bytes(name.encode())
        self.provider=Provider(self.root);self.allowed=True
        self.loop=LocalWorkLoop(self.root.parent/'tasks.sqlite',lambda _:self.root,lambda t:self.allowed,self.provider)
        self.principal={'kind':'synthetic'}
        self.steps=[{'name':name,'edit':{'path':name+'.txt','expected_sha256':digest(name),'old':name,'new':name.upper()},'after':[] if name=='a' else ['a']} for name in ('a','b')]
    def tearDown(self):self.loop.close();self.temp.cleanup()
    def plan(self,**kwargs):return submit_plan(self.loop,'p',kwargs.get('key','plan'),'My plan',kwargs.get('steps',self.steps),self.principal)
    def test_atomic_plan_approval_dependency_execution_and_replay(self):
        plan=self.plan();first,second=plan['tasks'];self.assertTrue(plan['approval_required']);self.assertFalse(plan['started'])
        self.loop.approve('p',second['id'],second['version']);self.assertFalse(self.loop.worker.once())
        self.loop.approve('p',first['id'],first['version']);self.loop.worker.once();self.loop.worker.once()
        self.assertEqual(self.provider.calls,[first['id'],second['id']])
        self.assertEqual([t['id'] for t in self.plan()['tasks']],[first['id'],second['id']])
        self.assertFalse(self.loop.worker.once())
        self.assertEqual(self.loop.ledger.get('p',second['id'])['status'],'completed')
    def test_late_validation_failure_rolls_back_jobs_events_and_dependencies(self):
        self.steps[1]['edit']['expected_sha256']='0'*64
        with self.assertRaises(ValueError):self.plan()
        with self.loop.ledger.connection() as c:
            for table in ('jobs','dependencies','task_events','ownership'):
                self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.provider.calls,[])
    def test_plan_contract_conflict_cannot_add_partial_steps(self):
        self.plan();self.steps[1]['edit']['new']='different'
        with self.assertRaises(ValueError):self.plan()
        with self.loop.ledger.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],2)
    def test_invalid_graph_and_duplicate_files_rejected(self):
        invalid=[{**self.steps[0],'after':['b']},self.steps[1]]
        with self.assertRaises(ValueError):self.plan(steps=invalid)
        invalid=[self.steps[0],{**self.steps[1],'edit':self.steps[0]['edit']}]
        with self.assertRaises(ValueError):self.plan(steps=invalid)
        with self.assertRaises(ValueError):self.plan(steps=self.steps*5)
        self.allowed=False
        with self.assertRaises(PermissionError):self.plan()
    def test_legacy_standalone_fingerprint_remains_replayable(self):
        # Simulate a persisted pre-plan standalone task, including its old contract.
        edit=self.steps[0]['edit'];submission=hashlib.sha256(json.dumps({'edits':[edit],'principal':self.principal,'dependencies':()},sort_keys=True).encode()).hexdigest()
        payload={'targets':[{**edit,'result_sha256':digest('A')}],'_principal':self.principal,'_submission':submission,'_root':str(self.root)}
        old=self.loop.ledger.submit('p','legacy','local_exact_edit',payload,outputs=['a.txt'],approval=True,max_attempts=1)
        replay=self.loop.submit('p','legacy',[edit],principal=self.principal)
        self.assertEqual(old['id'],replay['id'])
