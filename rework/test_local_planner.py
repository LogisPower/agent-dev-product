import json,tempfile,unittest
from pathlib import Path
from local_planner import LocalPlanner,validate_response
from local_work_loop import LocalWorkLoop
from test_local_work_loop import Provider


class LocalPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'files';self.root.mkdir();(self.root/'a.txt').write_bytes(b'before')
        self.transport=Provider(self.root);self.calls=[];self.allowed=True
        self.loop=LocalWorkLoop(self.root.parent/'jobs.sqlite',lambda _:self.root,lambda _:self.allowed,self.transport)
        self.response={'title':'Change a','steps':[{'name':'a','path':'a.txt','old':'before','new':'after','after':[]}]}
        def provider(messages,timeout,json_output):
            self.assertEqual(timeout,90);self.assertTrue(json_output);self.calls.append(messages);return json.dumps(self.response)
        self.planner=LocalPlanner(self.loop,provider)
    def tearDown(self):self.loop.close();self.temp.cleanup()
    def request(self,key='goal'):return self.planner.submit('p',key,'Change before to after',['a.txt'],{'kind':'synthetic'})
    def test_goal_proposal_review_execution_and_duplicate_suppression(self):
        task=self.request();self.assertEqual(self.calls,[]);self.loop.worker.once()
        proposal=self.loop.ledger.get('p',task['id']);self.assertEqual(proposal['status'],'completed')
        self.assertEqual((self.root/'a.txt').read_bytes(),b'before');self.assertEqual(self.transport.calls,[])
        self.assertFalse(proposal['result']['executed']);self.assertTrue(proposal['result']['approval_required'])
        self.assertEqual(self.request()['id'],task['id']);self.assertFalse(self.loop.worker.once());self.assertEqual(len(self.calls),1)
        plan=self.planner.accept('p',task['id'],proposal['version']);child=plan['tasks'][0]
        self.assertEqual(child['status'],'approval');self.assertFalse(self.loop.worker.once())
        self.loop.approve('p',child['id'],child['version']);self.loop.worker.once()
        self.assertEqual((self.root/'a.txt').read_bytes(),b'after')
        replay=self.planner.accept('p',task['id'],proposal['version']);self.assertEqual(replay['tasks'][0]['id'],child['id'])
        self.assertFalse(self.loop.worker.once());self.assertEqual(self.transport.calls,[child['id']])
    def test_invalid_or_unselected_proposal_stays_reviewable_without_execution(self):
        self.response['steps'][0]['path']='outside.txt';task=self.request();self.loop.worker.once()
        state=self.loop.ledger.get('p',task['id']);self.assertEqual(state['status'],'needs_review')
        self.assertFalse(self.loop.worker.once());self.assertEqual(len(self.calls),1)
        with self.assertRaises(ValueError):self.planner.accept('p',task['id'],state['version'])
        self.assertEqual(self.transport.calls,[]);self.assertEqual((self.root/'a.txt').read_bytes(),b'before')
    def test_stale_current_file_rejects_acceptance_without_partial_plan(self):
        task=self.request();self.loop.worker.once();state=self.loop.ledger.get('p',task['id'])
        (self.root/'a.txt').write_bytes(b'new external version')
        with self.assertRaises(ValueError):self.planner.accept('p',task['id'],state['version'])
        with self.loop.ledger.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
    def test_source_change_during_planning_withholds_proposal(self):
        original=self.planner.provider
        def changed(*args,**kwargs):
            value=original(*args,**kwargs);(self.root/'a.txt').write_bytes(b'concurrent edit');return value
        self.planner.provider=changed;task=self.request();self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review')
        self.assertEqual(self.transport.calls,[])
    def test_cancel_and_revocation_do_not_generate_or_execute(self):
        task=self.request();self.loop.ledger.cancel('p',task['id']);self.loop.worker.once();self.assertEqual(self.calls,[])
        task=self.request('revoked');self.allowed=False;self.loop.worker.once();self.assertEqual(self.calls,[])
        self.assertEqual(self.transport.calls,[])
    def test_bounds_and_duplicate_json_keys(self):
        (self.root/'a.txt').write_bytes(b'x'*12001)
        with self.assertRaises(ValueError):self.request()
        with self.assertRaises(ValueError):validate_response('{"title":"a","title":"b","steps":[]}',[])
        with self.assertRaises(ValueError):validate_response('explanation {"title":"x","steps":[]}',[])
