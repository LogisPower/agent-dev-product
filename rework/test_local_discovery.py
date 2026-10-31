import unittest
import test_local_planner as fixture
from local_discovery import LocalDiscovery

class DiscoveryTests(unittest.TestCase):
    setUp=fixture.LocalPlannerTests.setUp
    tearDown=fixture.LocalPlannerTests.tearDown
    def discover(self,key='find',query='before'):
        discovery=getattr(self.loop,'discovery',None) or LocalDiscovery(self.loop)
        task=discovery.submit('p',key,query,'',{'kind':'synthetic'});self.loop.worker.once()
        state=self.loop.ledger.get('p',task['id']);self.assertEqual(state['status'],'completed',state)
        return discovery,state
    def plan(self,d,t,allow=False):return d.plan('p',t['id'],t['version'],'Change before to after',['a.txt'],{'kind':'synthetic'},allow)
    def test_discovery_proposal_execution_and_replay(self):
        d,t=self.discover();self.assertEqual(t['result']['candidates'][0]['path'],'a.txt');self.assertEqual(self.calls,[])
        request=self.plan(d,t);self.assertEqual(request['payload']['_discovery'],t['id']);self.loop.worker.once()
        proposal=self.loop.ledger.get('p',request['id']);plan=self.planner.accept('p',request['id'],proposal['version']);child=plan['tasks'][0]
        self.assertEqual(child['status'],'approval');self.loop.approve('p',child['id'],child['version']);self.loop.worker.once()
        self.assertEqual((self.root/'a.txt').read_text(),'after');self.assertEqual(self.plan(d,t)['id'],request['id']);self.assertEqual(len(self.calls),1)
        again=d.submit('p','find','before','',{'kind':'synthetic'});self.assertEqual(again['id'],t['id']);self.assertFalse(self.loop.worker.once())
        d,t2=self.discover('after','after');self.assertTrue(t2['result']['candidates'][0]['completed_unchanged'])
        with self.assertRaisesRegex(ValueError,'completed work'):self.plan(d,t2)
        self.assertEqual(self.plan(d,t2,True)['status'],'queued')
    def test_stale_unfinished_and_scope(self):
        d,t=self.discover();(self.root/'a.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.plan(d,t)
        (self.root/'a.txt').write_bytes(b'before')
        pending=self.planner.submit('p','other','Other goal',['a.txt'],{'kind':'synthetic'})
        with self.assertRaisesRegex(ValueError,'unfinished'):self.plan(d,t)
        self.loop.ledger.cancel('p',pending['id']);self.allowed=False
        with self.assertRaises(PermissionError):self.plan(d,t)
    def test_bounds_hidden_recursive_and_missing(self):
        (self.root/'sub').mkdir();(self.root/'sub'/'match.txt').write_text('before')
        (self.root/'.hidden').mkdir();(self.root/'.hidden'/'a.txt').write_text('before')
        (self.root/'huge.txt').write_text('x'*12001)
        d,t=self.discover();self.assertEqual({x['path'] for x in t['result']['candidates']},{'a.txt','sub/match.txt'})
        self.assertTrue(t['result']['skipped'])
        for i in range(30):(self.root/f'file{i}.txt').write_text('before')
        _,bounded=self.discover('bounded');self.assertEqual(bounded['result']['files_read'],24);self.assertTrue(bounded['result']['truncated'])
        task=d.submit('p','missing','x','missing',{'kind':'synthetic'});self.loop.worker.once();state=self.loop.ledger.get('p',task['id'])
        self.assertEqual(state['status'],'completed');self.assertTrue(state['result']['truncated']);self.assertTrue(state['result']['skipped'])
    def test_root_rebinding_and_unknown_selection(self):
        d,t=self.discover()
        with self.assertRaises(ValueError):d.plan('p',t['id'],t['version'],'goal',['unknown.txt'],{'kind':'synthetic'})
        other=self.root.parent/'other';other.mkdir();(other/'a.txt').write_bytes(b'before');self.loop.resolve_project=lambda _:other
        with self.assertRaises(PermissionError):self.plan(d,t)
    def test_two_file_discovery_plan_dependency_and_restart(self):
        from local_work_loop import LocalWorkLoop
        from local_planner import LocalPlanner
        (self.root/'b.txt').write_bytes(b'before second')
        self.response['steps'].append({'name':'b','path':'b.txt','old':'before second','new':'after second','after':['a']})
        d,t=self.discover();request=d.plan('p',t['id'],t['version'],'Change both',['a.txt','b.txt'],{'kind':'synthetic'});self.loop.worker.once()
        proposal=self.loop.ledger.get('p',request['id']);children=self.planner.accept('p',request['id'],proposal['version'])['tasks']
        for child in children:self.loop.approve('p',child['id'],child['version'])
        self.loop.worker.once();self.assertEqual((self.root/'a.txt').read_text(),'after');self.assertEqual((self.root/'b.txt').read_text(),'before second')
        provider=self.planner.provider;self.loop.close();self.loop=LocalWorkLoop(self.root.parent/'jobs.sqlite',lambda _:self.root,lambda _:self.allowed,self.transport)
        self.planner=LocalPlanner(self.loop,provider);d=LocalDiscovery(self.loop);self.loop.worker.once()
        self.assertEqual((self.root/'b.txt').read_text(),'after second');self.assertEqual(len(self.transport.calls),2)
        self.assertEqual(d.plan('p',t['id'],t['version'],'Change both',['a.txt','b.txt'],{'kind':'synthetic'})['id'],request['id']);self.assertFalse(self.loop.worker.once());self.assertEqual(len(self.calls),1)
