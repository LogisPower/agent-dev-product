import hashlib,json,os,unittest,uuid
from unittest.mock import patch
import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from candidate_api import create_app

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['LOGIS_DISPATCH_TEST_DSN'];self.project='export-'+uuid.uuid4().hex;self.source='source-'+uuid.uuid4().hex
        with psycopg.connect(self.dsn) as c:
            c.execute('INSERT INTO logis_candidate.projects(id,name,context_policy) VALUES(%s,%s,%s)',(self.project,'Export fixture',Jsonb({'sources':['out-of-scope-project'],'internal_setting':'DO_NOT_EXPORT'})))
            c.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES(%s,%s,'conversation',%s,%s)",(self.source,self.project,hashlib.sha256(b'Preserved source').hexdigest(),Jsonb({'content':'Preserved source','internal_setting':'DO_NOT_EXPORT'})))
            c.execute("INSERT INTO logis_candidate.messages VALUES(%s,%s,%s,0,'user','Preserved source')",(uuid.uuid4().hex,self.project,self.source))
            for title in ('First','Second'):c.execute("INSERT INTO logis_candidate.objects(id,project_id,kind,status,payload) VALUES(%s,%s,'tasks','open',%s)",(uuid.uuid4().hex,self.project,Jsonb({'title':title})))
            c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload) VALUES(%s,%s,'local-build','completed',%s)",(uuid.uuid4().hex,self.project,Jsonb({'sha256':'a'*64,'_dispatch':{'principal':'DO_NOT_EXPORT','args':{'content':'DO_NOT_EXPORT'}}})))
        self.client=TestClient(create_app(self.dsn,{'reader':{'projects':[self.project],'write':False}},original_ui=True));self.headers={'Authorization':'Bearer reader'};self.url=f'/api/projects/{self.project}/export'
    def tearDown(self):self.client.close()
    def test_scoped_coherent_export_has_manifest_checksum_and_no_internal_credentials(self):
        response=self.client.get(self.url,headers=self.headers);self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(data['sections']['messages'][0]['content'],'Preserved source');self.assertEqual(data['manifest']['counts']['records'],2)
        self.assertFalse(data['manifest']['filesystem_backup']);self.assertNotIn('DO_NOT_EXPORT',response.text);self.assertNotIn('out-of-scope-project',response.text)
        self.assertEqual(response.headers['x-content-sha256'],hashlib.sha256(response.content).hexdigest());self.assertIn('attachment',response.headers['content-disposition'])
        self.assertEqual(self.client.get(self.url).status_code,401)
        self.assertEqual(self.client.get('/api/projects/not-scoped/export',headers=self.headers).status_code,404)
    def test_bounds_reject_instead_of_silent_truncation(self):
        with patch('project_export.MAX_ROWS',1):response=self.client.get(self.url,headers=self.headers)
        self.assertEqual(response.status_code,413);self.assertNotIn('sections',response.json())
        with patch('project_export.MAX_BYTES',50):response=self.client.get(self.url,headers=self.headers)
        self.assertEqual(response.status_code,413)
    def test_withdrawn_source_messages_excluded_and_records_preserved(self):
        with psycopg.connect(self.dsn) as c:c.execute('UPDATE logis_candidate.sources SET deleted_at=now() WHERE id=%s',(self.source,))
        data=self.client.get(self.url,headers=self.headers).json()
        self.assertEqual(data['sections']['messages'],[]);self.assertEqual(data['sections']['sources'],[]);self.assertEqual(len(data['sections']['records']),2)
