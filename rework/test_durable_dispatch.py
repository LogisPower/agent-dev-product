"""Canonical integration tests; require an explicitly supplied disposable database."""
import json,os,threading,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from candidate_api import create_app
from canonical_context import ContextStore
from context_guard import ContextGuard

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['LOGIS_DISPATCH_TEST_DSN']
        self.project='test-'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:c.execute("INSERT INTO logis_candidate.projects(id,name) VALUES(%s,'Synthetic dispatch test')",(self.project,))
        self.credentials={'test-writer':{'projects':[self.project],'write':True}}
        self.headers={'Authorization':'Bearer test-writer','Idempotency-Key':uuid.uuid4().hex}
        self.entered=threading.Event();self.release=threading.Event();self.calls=[]
        def build(messages):
            self.calls.append('build');self.entered.set()
            if not self.release.wait(5):raise TimeoutError('Synthetic provider deadline')
            return json.dumps({'html':'<!doctype html><html><body>Verified synthetic build</body></html>'})
        def chat(messages,**kwargs):
            self.calls.append('chat')
            return json.dumps({'goal':'answer','answer':'Synthetic reply with no actions.','actions':[]})
        self.app=create_app(self.dsn,self.credentials,background_chat=True,request_chat=chat,request_build=build,context_counter=lambda payload:len(json.dumps(payload))//3)
        self.app.state.local_langchain_enabled=False
        self.client=TestClient(self.app)
        self.artifact_patch=patch('candidate_build.DATA',Path(os.environ['LOGIS_DISPATCH_ARTIFACTS']))
        self.artifact_patch.start()

    def tearDown(self):
        self.release.set();self.app.state.durable_dispatch.close();self.client.close();self.artifact_patch.stop()

    def build(self,key=None):
        headers={**self.headers,'Idempotency-Key':key or uuid.uuid4().hex}
        r=self.client.post(f'/api/projects/{self.project}/builds',headers=headers,json={'prompt':'Build a tiny offline test card'})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def chat(self):
        r=self.client.post(f'/api/projects/{self.project}/chat',headers={**self.headers,'Idempotency-Key':uuid.uuid4().hex},json={'content':'Explain the synthetic project briefly'})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def run_state(self,run):
        with psycopg.connect(self.dsn) as c:
            row=c.execute('SELECT status,payload FROM logis_candidate.runs WHERE id=%s',(run,)).fetchone()
        return {'status':row[0],'payload':row[1]}

    def wait_state(self,run,wanted):
        until=time.monotonic()+8
        while time.monotonic()<until:
            state=self.run_state(run)
            if state['status'] in wanted:return state
            time.sleep(.03)
        self.fail(str(state))

    def test_build_chat_status_cancel_and_single_slot(self):
        with self.client:
            build=self.build();self.assertTrue(self.entered.wait(3))
            chat=self.chat()
            start=time.monotonic()
            response=self.client.get(f'/api/projects/{self.project}/dispatch',headers=self.headers)
            self.assertEqual(response.status_code,200);self.assertLess(time.monotonic()-start,1)
            self.assertEqual(self.calls,['build'])
            canceled=self.client.post(f'/api/projects/{self.project}/builds/{build["id"]}/cancel',headers=self.headers,json={})
            self.assertEqual(canceled.status_code,200)
            self.release.set()
            self.assertEqual(self.wait_state(build['id'],{'canceled','failed','completed'})['status'],'canceled')
            state=self.wait_state(chat['id'],{'completed','failed'})
            self.assertEqual(state['status'],'completed',state)
            self.assertEqual(self.calls,['build','chat'])
            self.assertFalse((Path(os.environ['LOGIS_DISPATCH_ARTIFACTS'])/build['id']).exists())

    def test_queued_restart_and_duplicate_no_second_build(self):
        job=self.build('stable-key')
        self.assertEqual(self.build('stable-key')['id'],job['id'])
        self.assertEqual(self.calls,[])
        # New app/dispatcher, same durable DB and same current principal registry.
        new=create_app(self.dsn,self.credentials,background_chat=True,request_build=lambda messages:json.dumps({'html':'<html><body>Recovered queued build</body></html>'}))
        with TestClient(new):
            state=self.wait_state(job['id'],{'completed','failed'})
        self.assertEqual(state['status'],'completed',state)
        self.assertTrue(state['payload']['sha256'])
        self.assertEqual(state['payload']['_dispatch']['attempts'],1)

    def test_active_restart_never_replays(self):
        job=self.build()
        with psycopg.connect(self.dsn) as c:
            c.execute("UPDATE logis_candidate.runs SET payload=jsonb_set(payload,'{_dispatch,phase}','\"active\"') WHERE id=%s",(job['id'],))
        with self.client:
            state=self.wait_state(job['id'],{'interrupted','failed','completed'})
        self.assertEqual(state['status'],'interrupted')
        self.assertEqual(self.calls,[])
        self.assertIn('args',state['payload']['_dispatch'])

    def test_revoked_principal_is_not_replayed(self):
        job=self.build();self.credentials.clear()
        with self.client:state=self.wait_state(job['id'],{'failed','completed'})
        self.assertEqual(state['status'],'failed');self.assertEqual(self.calls,[])

    def test_compaction_failure_persists_and_originals_survive(self):
        job=self.chat();dispatcher=self.app.state.durable_dispatch
        with dispatcher.db(False) as c:
            c.execute("UPDATE logis_candidate.runs SET payload=jsonb_set(payload,'{_dispatch,phase}','\"active\"') WHERE id=%s",(job['id'],))
        store=ContextStore(dispatcher.db,self.project)
        guard=ContextGuard(store,job['id'],None,lambda p:len(json.dumps(p)),200,20)
        messages=[{'role':'system','content':'preserve authority'},{'role':'user','content':'x'*1000}]
        calls=[]
        for _ in range(3):
            with self.assertRaises(ValueError):guard.fit(messages,[],lambda m:calls.append(1) or '')
        state=self.run_state(job['id'])
        self.assertEqual(len(calls),2)
        self.assertEqual(state['payload']['compaction_attempts'],2)
        self.assertEqual(len(state['payload']['context_originals']),1)

    def test_scope_and_queue_status_excludes_principal_inputs(self):
        job=self.build()
        value=self.client.get(f'/api/projects/{self.project}/dispatch',headers=self.headers).json()
        self.assertNotIn('principal',json.dumps(value));self.assertNotIn('test-writer',json.dumps(value))
        self.assertEqual(self.client.get('/api/projects/other/dispatch',headers=self.headers).status_code,404)

    def test_template_tokenizer_counts_complete_prompt_without_inference(self):
        from canonical_context import provider_tokens
        from unittest.mock import MagicMock
        messages=[{'role':'system','content':'schema'*9000},{'role':'user','content':'latest request'}]
        replies=[{'prompt':'rendered complete template'},{'tokens':[1,2,3]}]
        seen=[]
        def respond(request,timeout):
            seen.append((request.full_url,json.loads(request.data)))
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(replies.pop(0)).encode();return response
        with patch('urllib.request.urlopen',side_effect=respond):
            self.assertEqual(provider_tokens({'messages':messages,'tools':[]}),67)
        self.assertTrue(seen[0][0].endswith('/apply-template'))
        self.assertEqual(seen[0][1]['messages'],messages)
        self.assertTrue(seen[1][0].endswith('/tokenize'))
        self.assertEqual(seen[1][1]['content'],'rendered complete template')

    def test_file_worker_rechecks_queued_credential(self):
        import tempfile
        from foundation_runtime import Foundation
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);files=folder/'files';files.mkdir()
            runtime=Foundation(folder/'queue.sqlite',lambda project:files)
            app=create_app(self.dsn,self.credentials,foundation=runtime)
            client=TestClient(app)
            response=client.post(f'/api/projects/{self.project}/foundation/submit',headers=self.headers,json={'kind':'file_read','key':'scope-test','payload':{'path':'missing.txt'}})
            self.assertEqual(response.status_code,200,response.text)
            task=response.json();self.credentials.clear()
            runtime.worker.once()
            self.assertEqual(runtime.ledger.get(self.project,task['id'])['status'],'failed')
            client.close()

if __name__=='__main__':unittest.main(verbosity=2)
