import tempfile,unittest
from pathlib import Path
from local_progress import ProgressGuard
from local_planning_context import planning_context
from local_work_loop import LocalWorkLoop,digest
from test_local_work_loop import Provider


class ProgressTests(unittest.TestCase):
    def test_transport_reports_new_activity_after_old_terminal_without_arguments(self):
        from local_dsh_transport import DshTransport
        def rpc(method,args):
            if method=='session/projections':value={'asOfSeq':8,'values':{'sessionStats':{'steps':17}}}
            else:value={'records':[{'event':{'seq':5,'type':'turn/end','data':{'reason':{'kind':'completed'}}}},
                {'event':{'seq':8,'type':'tool/call','data':{'name':'read','arguments':'private-source-content'}}}]}
            return {'result':{'ok':True,'value':value}}
        result=DshTransport(rpc,'/workspace/p','p').poll('a'*32)
        self.assertEqual(result['status'],'running');self.assertEqual(result['steps'],17)
        self.assertEqual(len(result['tool_calls'][0]['signature']),64)
        self.assertNotIn('private-source-content',str(result))
    def test_duplicate_poll_page_not_a_repeated_tool_call(self):
        guard=ProgressGuard();value={'progress_seq':1,'steps':1,'tool_calls':[{'seq':1,'signature':'a'*64}]}
        for _ in range(5):self.assertIsNone(guard.observe(value))
        self.assertEqual(guard.calls,1)
        for seq in (2,3):self.assertIsNone(guard.observe({**value,'progress_seq':seq,'tool_calls':[{'seq':seq,'signature':'a'*64}]}))
        self.assertEqual(guard.observe({**value,'progress_seq':4,'tool_calls':[{'seq':4,'signature':'a'*64}]}),'repeated_tool_call')
    def test_step_stall_regression_and_missing_progress(self):
        now=[0];guard=ProgressGuard(lambda:now[0])
        self.assertIsNone(guard.observe({'progress_seq':1,'steps':1}));now[0]=180
        self.assertEqual(guard.observe({'progress_seq':1,'steps':1}),'progress_stalled')
        self.assertEqual(guard.observe({'progress_seq':0,'steps':1}),'progress_regressed')
        self.assertEqual(guard.observe({}),'invalid_progress')
        self.assertEqual(ProgressGuard().observe({'progress_seq':100,'steps':17}),'step_budget_exceeded')


class PlanningEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'files';self.root.mkdir()
        (self.root/'a.txt').write_bytes(b'before');self.provider=Provider(self.root)
        self.loop=LocalWorkLoop(self.root.parent/'jobs.sqlite',lambda _:self.root,lambda _:True,self.provider,timeout=1)
        self.edit={'path':'a.txt','expected_sha256':digest('before'),'old':'before','new':'after'}
    def tearDown(self):self.loop.close();self.temp.cleanup()
    def approved(self):
        task=self.loop.submit('p','one',[self.edit],principal={'kind':'synthetic'});self.loop.approve('p',task['id'],task['version']);return task
    def test_completed_evidence_current_drift_and_no_duplicate_provider_call(self):
        task=self.approved();self.loop.worker.once()
        context=planning_context(self.loop,'p',['a.txt']);target=context['tasks'][0]['targets'][0]
        self.assertTrue(context['read_only']);self.assertTrue(target['recorded_verified']);self.assertTrue(target['current_matches_result'])
        self.assertEqual(context['tasks'][0]['guidance'],'completed_do_not_reexecute')
        (self.root/'a.txt').write_bytes(b'changed elsewhere')
        self.assertFalse(planning_context(self.loop,'p',['a.txt'])['tasks'][0]['targets'][0]['current_matches_result'])
        self.assertEqual(planning_context(self.loop,'other',['a.txt'])['tasks'],[])
        self.loop.submit('p','one',[self.edit],principal={'kind':'synthetic'})
        self.assertFalse(self.loop.worker.once());self.assertEqual(self.provider.calls,[task['id']])
    def test_step_budget_cancels_and_retains_review_evidence(self):
        task=self.approved()
        self.provider.poll=lambda request:{'request_id':request,'status':'running','progress_seq':80,'steps':17,'tool_calls':[]}
        self.loop.worker.once();state=self.loop.ledger.get('p',task['id'])
        self.assertEqual(state['status'],'needs_review');self.assertEqual(state['checkpoint']['reason'],'step_budget_exceeded')
        self.assertEqual(self.provider.cancels,[task['id']]);self.assertFalse(self.loop.worker.once())
        context=planning_context(self.loop,'p',['a.txt'])
        self.assertEqual(context['tasks'][0]['guidance'],'review_required_do_not_resubmit')
        self.assertFalse(context['tasks'][0]['targets'][0]['recorded_verified'])
        self.assertTrue(context['tasks'][0]['targets'][0]['current_matches_result'])
        with self.assertRaises(ValueError):self.loop.reconcile('p',task['id'],state['version'])
    def test_packet_contains_bounded_current_evidence_without_source_history(self):
        task=self.approved();original=self.provider.submit;captured=[]
        def submit(request,packet):captured.append(packet);return original(request,packet)
        self.provider.submit=submit;self.loop.worker.once();evidence=captured[0]['planning_evidence']
        self.assertEqual(evidence['files']['a.txt']['sha256'],digest('before'))
        self.assertEqual(evidence['tasks'],[]);self.assertNotIn('content',evidence['files']['a.txt'])
        self.assertTrue(evidence['read_only'])
