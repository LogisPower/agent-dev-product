import json,tempfile,unittest
from pathlib import Path
from local_analysis import LocalAnalysis,verify_evidence
from local_planner import LocalPlanner
from local_work_loop import LocalWorkLoop
from test_local_work_loop import Provider


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'files';self.root.mkdir()
        (self.root/'large.txt').write_text('A'*17000);(self.root/'edit.txt').write_text('before')
        self.allowed=True;self.calls=[];self.mode='ok'
        self.loop=LocalWorkLoop(self.root.parent/'jobs.sqlite',lambda _:self.root,lambda _:self.allowed,Provider(self.root))
        LocalPlanner(self.loop,self.provider);self.analysis=LocalAnalysis(self.loop)
    def tearDown(self):self.loop.close();self.temp.cleanup()
    def provider(self,messages,**kwargs):
        self.calls.append(messages)
        self.assertLessEqual(kwargs['timeout'],90)
        if self.mode=='cancel':
            from provider_cancel import current,ProviderCanceled
            self.loop.worker.stop.set();self.assertTrue(current.get()());raise ProviderCanceled('Canceled during inference')
        if self.mode=='error':raise TimeoutError('uncertain inference')
        data=json.loads(messages[1]['content'])
        if 'files' in data:return json.dumps({'title':'Edit','steps':[{'name':'edit','path':'edit.txt','old':'before','new':'after','after':[]}]})
        source=data['source'];a=source.get('source_span',[0,0])[0]
        if self.mode=='stop':self.loop.worker.stop.set()
        if self.mode=='stale':(self.root/'large.txt').write_text('changed')
        quotes=[] if 'children' in source else [{'text':'A','start':a,'end':a+1}]
        if self.mode=='bad_quote':quotes=[{'text':'not source','start':0,'end':10}]
        return json.dumps({'summary':'Unverified hint','quotes':quotes})
    def submit(self,key='one'):
        return self.analysis.submit('p',key,'Explain this source','large.txt',{'kind':'synthetic'})
    def done(self,task):return self.loop.ledger.get('p',task['id'])
    def test_three_calls_readonly_exact_evidence_and_idempotency(self):
        task=self.submit();self.loop.worker.once();done=self.done(task)
        self.assertEqual(done['status'],'completed');self.assertEqual(len(self.calls),3)
        self.assertTrue(done['result']['quotes_verified']);self.assertFalse(done['result']['summary_verified'])
        self.assertEqual((self.root/'large.txt').read_text(),'A'*17000)
        self.assertEqual(self.submit()['id'],task['id']);self.assertFalse(self.loop.worker.once())
        self.assertEqual(self.loop.transport.calls,[])
    def test_saved_node_survives_restart_without_repeating_call(self):
        task=self.submit();self.mode='stop';self.loop.worker.once();stopped=self.done(task)
        self.assertEqual(stopped['status'],'needs_review');self.assertEqual(len(self.calls),1)
        self.loop.close()
        self.loop=LocalWorkLoop(self.root.parent/'jobs.sqlite',lambda _:self.root,lambda _:self.allowed,Provider(self.root))
        LocalPlanner(self.loop,self.provider);self.analysis=LocalAnalysis(self.loop);self.mode='ok'
        resumed=self.analysis.resume('p',task['id'],stopped['version']);self.loop.worker.once()
        self.assertEqual(self.done(resumed)['status'],'completed');self.assertEqual(len(self.calls),3)
    def test_uncertain_call_not_replayed_and_invalid_quote_rejected(self):
        for mode in ('error','bad_quote'):
            self.mode=mode;task=self.submit(mode);self.loop.worker.once();done=self.done(task)
            self.assertEqual(done['status'],'needs_review')
            with self.assertRaises(ValueError):self.analysis.resume('p',task['id'],done['version'])
        self.assertEqual(len(self.calls),2)
    def test_bounds_scope_and_changed_source_stop_without_more_calls(self):
        (self.root/'big.txt').write_text('x'*32001)
        with self.assertRaises(ValueError):self.analysis.submit('p','big','q','big.txt',{})
        task=self.submit();self.mode='stale';self.loop.worker.once()
        self.assertEqual(self.done(task)['status'],'needs_review');self.assertEqual(len(self.calls),1)
        self.allowed=False
        with self.assertRaises(PermissionError):self.submit('denied')
    def test_analysis_to_exact_plan_rechecks_source_and_separate_approval(self):
        task=self.submit();self.loop.worker.once();done=self.done(task)
        plan=self.analysis.plan('p',task['id'],done['version'],'Change before to after',['edit.txt'],{'kind':'synthetic'})
        self.loop.worker.once();planned=self.done(plan);self.assertEqual(planned['status'],'completed')
        accepted=self.loop.planner.accept('p',plan['id'],planned['version'])
        self.assertEqual(accepted['tasks'][0]['status'],'approval');self.assertEqual((self.root/'edit.txt').read_text(),'before')
        (self.root/'large.txt').write_text('changed')
        with self.assertRaises(ValueError):self.loop.planner.accept('p',plan['id'],planned['version'])
        edit=accepted['tasks'][0];self.loop.approve('p',edit['id'],edit['version']);self.loop.worker.once()
        self.assertEqual(self.done(edit)['status'],'failed');self.assertEqual(self.loop.transport.calls,[])
    def test_canceled_queued_analysis_makes_no_calls(self):
        task=self.submit();self.loop.ledger.cancel('p',task['id']);self.loop.worker.once();self.assertEqual(self.calls,[])
    def test_active_cancellation_and_elapsed_budget(self):
        from unittest.mock import patch
        task=self.submit();self.mode='cancel';self.loop.worker.once();done=self.done(task)
        self.assertEqual(done['status'],'needs_review')
        with self.assertRaises(ValueError):self.analysis.resume('p',task['id'],done['version'])
        self.loop.worker.stop.clear();other=self.submit('deadline')
        with patch('local_analysis.time.monotonic',side_effect=[0,301]):self.loop.worker.once()
        self.assertEqual(self.done(other)['status'],'failed');self.assertEqual(len(self.calls),1)

