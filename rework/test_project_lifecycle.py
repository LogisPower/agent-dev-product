import json,os,tempfile,time,unittest,uuid,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import psycopg
from fastapi.testclient import TestClient
from candidate_api import create_app
from foundation_runtime import Foundation

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['LOGIS_DISPATCH_TEST_DSN'];self.project='lifecycle-'+uuid.uuid4().hex
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        with psycopg.connect(self.dsn) as c:c.execute('INSERT INTO logis_candidate.projects(id,name) VALUES(%s,%s)',(self.project,'Original name'))
        self.credentials={'synthetic-owner':{'projects':[self.project],'write':True},'synthetic-reader':{'projects':[self.project],'write':False}}
        self.client=TestClient(create_app(self.dsn,self.credentials,original_ui=True))
        self.headers={'Authorization':'Bearer synthetic-owner'};self.url=f'/api/projects/{self.project}/settings'
    def tearDown(self):self.client.close();self.temp.cleanup()
    def update(self,body,key=None):return self.client.patch(self.url,headers={**self.headers,'Idempotency-Key':key or uuid.uuid4().hex},json=body)

    def test_version_idempotency_readonly_and_no_scope_expansion(self):
        body={'name':'Renamed safely','expected_version':1};key=uuid.uuid4().hex
        first=self.update(body,key);self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(self.update(body,key).json()['replayed'])
        self.assertEqual(self.update({**body,'name':'Lost edit'}).status_code,409)
        self.assertEqual(self.update({**body,'name':'Key misuse'},key).status_code,409)
        self.assertEqual(self.client.patch(self.url,headers={'Authorization':'Bearer synthetic-reader','Idempotency-Key':uuid.uuid4().hex},json={'brief':'Denied','expected_version':2}).status_code,403)
        self.assertEqual(self.update({'expected_version':2,'context_policy':{'sources':['not-scoped']}}).status_code,404)
        self.assertEqual(self.client.get(self.url,headers=self.headers).json()['name'],'Renamed safely')

    def test_archive_trash_restore_no_data_loss(self):
        body={'kind':'cases','title':'Preserved evidence','detail':'Keep this','status':'open'}
        created=self.client.post(f'/api/projects/{self.project}/objects',headers={**self.headers,'Idempotency-Key':uuid.uuid4().hex},json=body)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual(self.update({'expected_version':1,'archived':True}).status_code,200)
        trashed=self.update({'expected_version':2,'trash':True});self.assertTrue(trashed.json()['trashed'])
        restored=self.update({'expected_version':3,'trash':False});self.assertTrue(restored.json()['archived']);self.assertFalse(restored.json()['trashed'])
        self.assertEqual(self.update({'expected_version':4,'archived':False}).status_code,200)
        rows=self.client.get(f'/api/projects/{self.project}/objects',headers=self.headers).json()
        self.assertEqual(rows[0]['payload']['detail'],'Keep this')
        with psycopg.connect(self.dsn) as c:
            count=c.execute("SELECT count(*) FROM logis_candidate.events WHERE permissions_scope=%s AND event_type='project.metadata_updated'",(self.project,)).fetchone()[0]
        self.assertEqual(count,4)

    def test_active_work_blocks_archive_and_paging_bounds(self):
        with psycopg.connect(self.dsn) as c:c.execute("INSERT INTO logis_candidate.runs(id,project_id,status,payload) VALUES(%s,%s,'running','{}')",(uuid.uuid4().hex,self.project))
        self.assertEqual(self.update({'expected_version':1,'trash':True}).status_code,409)
        path=f'/api/projects/{self.project}/conversation'
        self.assertEqual(self.client.get(path+'?limit=101',headers=self.headers).status_code,422)
        self.assertEqual(self.client.get(path,headers=self.headers).json()['messages'],[])

    def test_archived_project_blocks_queued_file_effect(self):
        files=self.root/'files';files.mkdir();foundation=Foundation(self.root/'ledger.sqlite',lambda _:files)
        app=create_app(self.dsn,self.credentials,foundation=foundation,original_ui=True)
        with TestClient(app) as client:
            # Stop the worker so the approved write remains queued until archive commits.
            foundation.close()
            base=f'/api/projects/{self.project}/foundation'
            task=client.post(base+'/submit',headers=self.headers,json={'key':'synthetic-write','kind':'file_write','payload':{'path':'result.txt','content':'Must not be written'}}).json()
            self.assertEqual(client.post(base+'/approve',headers=self.headers,json={'task':task['id'],'version':task['version']}).status_code,200)
            self.assertEqual(self.update({'expected_version':1,'archived':True}).status_code,200)
            foundation.worker.once()
            self.assertFalse((files/'result.txt').exists())
            self.assertEqual(foundation.ledger.get(self.project,task['id'])['status'],'failed')

    def test_existing_device_session_requires_csrf_and_revocation_applies(self):
        from device_sessions import Store,digest,COOKIE,ORIGIN
        store=Store(self.root/'devices.sqlite');secret='synthetic-cookie-secret';identifier=uuid.uuid4().hex
        with store.db() as c:c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)',(identifier,digest(secret),digest('synthetic-owner'),json.dumps(self.credentials['synthetic-owner']),time.time()+600,'Synthetic device',time.time()))
        with TestClient(create_app(self.dsn,self.credentials,device_store=store.path,original_ui=True),base_url=ORIGIN) as client:
            client.cookies.set(COOKIE,secret)
            session=client.get('/api/device/session');self.assertEqual(session.status_code,200,session.text)
            body={'name':'Device edit','expected_version':1};headers={'Origin':ORIGIN,'Idempotency-Key':uuid.uuid4().hex}
            self.assertEqual(client.patch(self.url,headers=headers,json=body).status_code,403)
            headers['X-Logis-CSRF']=session.json()['csrf']
            self.assertEqual(client.patch(self.url,headers=headers,json=body).status_code,200)
            store.logout(secret)
            # Existing device API reports Denied as 409; no data is returned.
            revoked=client.get(self.url)
            self.assertEqual(revoked.status_code,409)
            self.assertIn('detail',revoked.json())

    def test_inflight_file_effect_and_archive_are_serialized(self):
        from task_worker import file_write
        files=self.root/'serial-files';files.mkdir();foundation=Foundation(self.root/'serial.sqlite',lambda _:files)
        entered=threading.Event();release=threading.Event()
        def held_write(attempt,workspace,payload):
            entered.set()
            if not release.wait(4):raise TimeoutError('Synthetic test release deadline')
            return file_write(attempt,workspace,payload)
        foundation.worker.handlers={**foundation.worker.handlers,'file_write':held_write}
        client=TestClient(create_app(self.dsn,self.credentials,foundation=foundation,original_ui=True))
        try:
            base=f'/api/projects/{self.project}/foundation'
            task=client.post(base+'/submit',headers=self.headers,json={'key':'serialized-write','kind':'file_write','payload':{'path':'result.txt','content':'Committed before archive'}}).json()
            self.assertEqual(client.post(base+'/approve',headers=self.headers,json={'task':task['id'],'version':task['version']}).status_code,200)
            with ThreadPoolExecutor(max_workers=2) as pool:
                work=pool.submit(foundation.worker.once)
                try:
                    self.assertTrue(entered.wait(2))
                    archive=pool.submit(self.update,{'expected_version':1,'archived':True})
                    time.sleep(.1)
                    self.assertFalse(archive.done(),'Archive must wait for the file effect lock')
                finally:release.set()
                self.assertTrue(work.result(timeout=4))
                self.assertEqual(archive.result(timeout=4).status_code,200)
            self.assertEqual((files/'result.txt').read_text(),'Committed before archive')
            self.assertTrue(self.client.get(self.url,headers=self.headers).json()['archived'])
        finally:release.set();client.close();foundation.close()
