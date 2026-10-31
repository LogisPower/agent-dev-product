import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from activation_adapter import Binding
from local_provider_adapters import existing_slot,make_existing_adapters,CoordinatedDshTransport
from existing_dsh_rpc import ExistingDshRPC
from inference_gate import InferenceBusyError

class ProviderAdaptersTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'project';self.root.mkdir();self.state=self.base/'private';self.state.mkdir();self.lock=self.base/'inference.lock';self.lock.write_bytes(b'0')
        self.binding=Binding('p',self.root,'/workspace/test',self.state);self.calls=[];self.complete=False
    def tearDown(self):self.temp.cleanup()
    def rpc(self,method,args):
        self.calls.append(method)
        if method=='session/create':value={'sessionId':args['request']['sessionId']}
        elif method=='session/prompt':value={'accepted':True}
        elif method=='session/projections':value={'asOfSeq':1,'values':{'sessionStats':{'steps':1}}}
        elif method=='session/page':value={'records':[{'event':{'seq':1,'type':'turn/end' if self.complete else 'turn/start','data':{'reason':{'kind':'completed'}}}}]}
        else:value={}
        return {'result':{'ok':True,'value':value}}
    def test_existing_lock_no_creation_content_change_or_double_admission(self):
        before=self.lock.stat().st_mtime_ns
        with existing_slot(self.lock):
            with self.assertRaises(InferenceBusyError):
                with existing_slot(self.lock):pass
        self.assertEqual(self.lock.read_bytes(),b'0');self.assertEqual(self.lock.stat().st_mtime_ns,before)
        absent=self.base/'absent.lock'
        with self.assertRaises(OSError):
            with existing_slot(absent):pass
        self.assertFalse(absent.exists())
    def test_text_build_planner_share_explicit_lock_without_constructor_calls(self):
        with patch('local_provider_adapters.resident_idle') as probe,patch('chat_transport.completion',return_value='answer') as completion:
            adapters=make_existing_adapters(self.binding,self.lock,self.rpc);probe.assert_not_called();completion.assert_not_called()
            self.assertEqual(adapters.request_chat([],timeout=90),'answer');self.assertEqual(completion.call_args.kwargs,{'timeout':90,'json_output':False})
            adapters.request_build([]);self.assertEqual(completion.call_args.kwargs,{'timeout':180,'json_output':True})
            with existing_slot(self.lock):
                with self.assertRaises(InferenceBusyError):adapters.local_planner([],timeout=90,json_output=True)
            from provider_cancel import cancellation,ProviderCanceled
            count=completion.call_count
            with cancellation(lambda:True):
                with self.assertRaises(ProviderCanceled):adapters.request_chat([])
            self.assertEqual(completion.call_count,count)
    def test_dsh_holds_slot_until_terminal_and_cancels_only_owned_request(self):
        transport=CoordinatedDshTransport(self.rpc,self.binding.container_root,'p',self.lock,probe=lambda:None);request='a'*32;packet={'request_id':request,'project':'p','targets':[]}
        self.assertTrue(transport.submit(request,packet)['accepted'])
        self.assertEqual(transport.poll(request)['status'],'running')
        with self.assertRaises(InferenceBusyError):
            with existing_slot(self.lock):pass
        self.complete=True;self.assertEqual(transport.poll(request)['status'],'completed')
        with existing_slot(self.lock):pass
        self.complete=False;transport.submit(request,packet);transport.cancel(request);self.assertEqual(self.calls[-1],'session/cancel')
        with existing_slot(self.lock):pass
    def test_failed_probe_and_rpc_release_lock(self):
        transport=CoordinatedDshTransport(self.rpc,self.binding.container_root,'p',self.lock,probe=lambda:(_ for _ in ()).throw(InferenceBusyError('busy')))
        with self.assertRaises(InferenceBusyError):transport.submit('b'*32,{'request_id':'b'*32,'project':'p'})
        self.assertEqual(self.calls,[])
        with existing_slot(self.lock):pass
        transport=CoordinatedDshTransport(lambda *a:{'result':{'ok':True,'value':None}},self.binding.container_root,'p',self.lock,probe=lambda:None)
        with self.assertRaises(ValueError):transport.submit('b'*32,{'request_id':'b'*32,'project':'p'})
        with existing_slot(self.lock):pass

    def test_admission_busy_then_ready_submits_once(self):
        from task_worker import Canceled
        class Attempt:
            cancelled=threading.Event()
            def check(self):
                if self.cancelled.is_set():raise Canceled()
            def checkpoint(self,value):self.check()
        attempt=Attempt();probes=[]
        def probe():
            probes.append(True)
            if len(probes)==1:raise InferenceBusyError('busy')
        transport=CoordinatedDshTransport(self.rpc,self.binding.container_root,'p',self.lock,probe=probe);request='c'*32
        transport.prepare(request,attempt,timeout=1,stopping=lambda:False)
        self.assertEqual(self.calls,[]);self.assertEqual(len(probes),2)
        transport.submit(request,{'request_id':request,'project':'p','targets':[]});transport.cancel(request)
        self.assertEqual(self.calls.count('session/prompt'),1)
        self.assertFalse(transport.pending);self.assertFalse(transport.leases)
    def test_admission_timeout_cancel_and_stop_make_no_remote_calls(self):
        from task_worker import Canceled
        for mode in ('timeout','cancel','stop'):
            with self.subTest(mode=mode):
                class Attempt:
                    cancelled=threading.Event()
                    def check(self):
                        if self.cancelled.is_set():raise Canceled()
                    def checkpoint(self,value):self.check()
                attempt=Attempt()
                def probe():
                    if mode=='cancel':attempt.cancelled.set()
                    raise InferenceBusyError('busy')
                transport=CoordinatedDshTransport(self.rpc,self.binding.container_root,'p',self.lock,probe=probe);request='d'*32
                with self.assertRaises((TimeoutError,Canceled,RuntimeError)):
                    transport.prepare(request,attempt,timeout=.01,stopping=lambda:mode=='stop')
                transport.cancel(request)
                self.assertEqual(self.calls,[]);self.assertFalse(transport.pending);self.assertFalse(transport.leases)
                with existing_slot(self.lock):pass

class RpcTests(unittest.TestCase):
    def test_loopback_cookie_reader_no_redirect_and_method_bounds(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append({'path':self.path,'cookie':self.headers.get('Cookie'),'body':json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
                if self.path.endswith('cancel'):
                    self.send_response(302);self.send_header('Location','http://example.invalid/secret');self.end_headers();return
                raw=json.dumps({'result':{'ok':True,'value':{'items':[]}}}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*a):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        cookie=['fixture=first']
        try:
            client=ExistingDshRPC(server.server_port,lambda:cookie[0]);self.assertTrue(client('session/list',{'_request':{}})['result']['ok'])
            cookie[0]='fixture=second';client('session/list',{'_request':{}});self.assertEqual(received[-1]['cookie'],'fixture=second')
            with self.assertRaises(RuntimeError):client('session/cancel',{'request':{'sessionId':'fixture'}})
            self.assertEqual(len(received),3)
            with self.assertRaises(ValueError):client('config/set',{})
            cookie[0]='bad\r\nheader'
            with self.assertRaises(ValueError):client('session/list',{})
        finally:server.shutdown();server.server_close();thread.join()
