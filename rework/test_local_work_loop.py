import tempfile, unittest
from pathlib import Path
from local_work_loop import LocalWorkLoop, digest


class Provider:
    def __init__(self, root):
        self.root=root;self.calls=[];self.cancels=[];self.status='completed';self.uncertain=False;self.change=True
    def submit(self, request, packet):
        self.calls.append(request)
        if self.change:
            for target in packet['targets']:
                p=self.root/target['path'];p.write_bytes(p.read_bytes().decode().replace(target['old'],target['new'],1).encode())
        if self.uncertain:raise TimeoutError('Response lost after effect')
        return {'request_id':request,'accepted':True}
    def poll(self, request):return {'request_id':request,'status':self.status}
    def cancel(self, request):self.cancels.append(request)


class LocalLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'files';self.root.mkdir()
        (self.root/'one.txt').write_bytes(b'original\r\n');self.allowed=True
        self.provider=Provider(self.root)
        self.loop=LocalWorkLoop(Path(self.temp.name)/'local.sqlite',lambda p:self.root,
            lambda task:self.allowed and task['project']=='p',self.provider,timeout=1)
        self.edits=[{'path':'one.txt','expected_sha256':digest('original\r\n'),'old':'original','new':'changed'}]
    def tearDown(self):self.loop.close();self.temp.cleanup()
    def submit(self,key='one',edits=None,dependencies=()):
        return self.loop.submit('p',key,edits or self.edits,principal={'kind':'synthetic'},dependencies=dependencies)
    def approved(self):
        task=self.submit();self.loop.approve('p',task['id'],task['version']);return task
    def test_approval_exact_effect_and_idempotent_replay(self):
        task=self.submit();self.assertFalse(self.loop.worker.once());self.assertEqual(self.provider.calls,[])
        self.loop.approve('p',task['id'],task['version']);self.assertTrue(self.loop.worker.once())
        done=self.loop.ledger.get('p',task['id']);self.assertEqual(done['status'],'completed')
        self.assertEqual((self.root/'one.txt').read_bytes(),b'changed\r\n')
        self.assertEqual(done['artifacts'][0]['sha256'],digest('changed\r\n'))
        self.assertEqual(self.submit()['id'],task['id']);self.assertFalse(self.loop.worker.once())
        self.assertEqual(self.provider.calls,[task['id']])
        with self.assertRaises(ValueError):self.submit(edits=[{**self.edits[0],'new':'different'}])
    def test_uncertain_submit_never_replayed_and_explicit_reconcile(self):
        task=self.approved();self.provider.uncertain=True;self.loop.worker.once()
        state=self.loop.ledger.get('p',task['id']);self.assertEqual(state['status'],'needs_review')
        self.assertEqual(state['checkpoint']['request_id'],task['id'])
        self.assertEqual(self.provider.cancels,[task['id']]);self.assertFalse(self.loop.worker.once())
        self.loop.close()
        self.loop=LocalWorkLoop(Path(self.temp.name)/'local.sqlite',lambda p:self.root,
            lambda task:self.allowed,self.provider,timeout=1)
        self.assertFalse(self.loop.worker.once())
        result=self.loop.reconcile('p',task['id'],state['version']);self.assertEqual(result['status'],'completed')
        self.assertEqual(self.provider.calls,[task['id']]);self.assertFalse(result['result']['reexecuted'])
    def test_claim_of_completion_without_bytes_requires_review(self):
        task=self.approved();self.provider.change=False;self.loop.worker.once()
        state=self.loop.ledger.get('p',task['id']);self.assertEqual(state['status'],'needs_review')
        with self.assertRaises(ValueError):self.loop.reconcile('p',task['id'],state['version'])
    def test_stale_version_or_withdrawn_scope_prevents_submission(self):
        task=self.approved();(self.root/'one.txt').write_text('someone else')
        self.loop.worker.once();self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'failed')
        self.allowed=False
        with self.assertRaises(PermissionError):self.submit('revoked')
    def test_canceled_queued_job_does_not_call_provider(self):
        task=self.approved();self.loop.ledger.cancel('p',task['id']);self.loop.worker.once()
        self.assertEqual(self.provider.calls,[])
    def test_binding_change_before_dispatch_prevents_provider_call(self):
        task=self.approved();other=self.root.parent/'other';other.mkdir()
        self.loop.resolve_project=lambda p:other
        self.loop.worker.once()
        self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'failed')
    def test_admission_timeout_is_known_unsubmitted_failure(self):
        task=self.approved()
        def prepare(*args,**kwargs):raise TimeoutError('busy before submission')
        self.provider.prepare=prepare;self.loop.worker.once()
        state=self.loop.ledger.get('p',task['id'])
        self.assertEqual(state['status'],'failed');self.assertFalse(state['result']['effect_started'])
        self.assertEqual(self.provider.calls,[]);self.assertFalse(self.loop.worker.once())
    def test_admission_rechecks_scope_binding_and_file_versions(self):
        for change in ('scope','binding','file'):
            with self.subTest(change=change):
                self.allowed=True;self.loop.resolve_project=lambda p:self.root
                (self.root/'one.txt').write_bytes(b'original\r\n')
                task=self.submit(change);self.loop.approve('p',task['id'],task['version'])
                def prepare(*args,**kwargs):
                    if change=='scope':self.allowed=False
                    elif change=='binding':
                        other=self.root.parent/'other';other.mkdir();self.loop.resolve_project=lambda p:other
                    else:(self.root/'one.txt').write_bytes(b'concurrent edit')
                self.provider.prepare=prepare;self.loop.worker.once()
                self.assertEqual(self.provider.calls,[])
                self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'failed')
    def test_scope_withdrawal_while_running_requests_cancel(self):
        task=self.approved()
        def poll(request):
            self.allowed=False
            return {'request_id':request,'status':'completed'}
        self.provider.poll=poll
        self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review')
        self.assertEqual(self.provider.cancels,[task['id']])
    def test_timeout_requests_cancel_and_preserves_uncertain_effect(self):
        task=self.approved();self.provider.status='running';self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review')
        self.assertEqual(self.provider.cancels,[task['id']])
        self.assertEqual((self.root/'one.txt').read_bytes(),b'changed\r\n')
    def test_dependency_waits_for_verified_local_artifact(self):
        first=self.approved();(self.root/'two.txt').write_bytes(b'second')
        second=self.submit('two',[{'path':'two.txt','expected_sha256':digest('second'),'old':'second','new':'verified next'}],
            dependencies=[{'task':first['id'],'path':'one.txt'}])
        self.loop.approve('p',second['id'],second['version'])
        self.loop.worker.once();self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',second['id'])['status'],'completed')
        self.assertEqual(self.provider.calls,[first['id'],second['id']])

    def test_dsh_bridge_binds_session_and_checks_completion_events(self):
        from local_dsh_transport import DshTransport
        calls=[];request='a'*32
        def rpc(method,args):
            calls.append((method,args))
            value={'sessionId':'logis-work-'+request} if method=='session/create' else {'accepted':True} if method=='session/prompt' else {'asOfSeq':10} if method=='session/projections' else {'records':[{'event':{'type':'turn/end','data':{'reason':{'kind':'completed'}}}}]} if method=='session/page' else {}
            return {'result':{'ok':True,'value':value}}
        transport=DshTransport(rpc,'/workspace/isolated','p')
        with self.assertRaises(ValueError):transport.submit(request,{'request_id':request,'project':'other','targets':[]})
        self.assertTrue(transport.submit(request,{'request_id':request,'project':'p','targets':[]})['accepted'])
        self.assertEqual(transport.poll(request)['status'],'completed');transport.cancel(request)
        self.assertEqual(calls[0][1]['request']['cwd'],'/workspace/isolated')
        self.assertEqual(calls[-1][1]['request']['sessionId'],'logis-work-'+request)
        with self.assertRaises(ValueError):transport.poll('../unknown')
