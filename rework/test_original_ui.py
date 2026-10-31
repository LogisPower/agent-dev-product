"""Original shell serving and canonical data access boundaries."""
import os,unittest,uuid
import psycopg
from fastapi.testclient import TestClient
from candidate_api import create_app

class OriginalUITests(unittest.TestCase):
    def test_opt_in_assets_do_not_expose_secrets_or_grant_scope(self):
        dsn=os.environ['LOGIS_DISPATCH_TEST_DSN']
        credentials={'synthetic-ui-secret':{'projects':[],'write':False}}
        with TestClient(create_app(dsn,credentials,original_ui=True)) as client:
            shell=client.get('/logis')
            self.assertEqual(shell.status_code,200)
            self.assertIn('PERSONAL OPERATING SYSTEM',shell.text)
            self.assertIn('/logis-assets/canonical-ui.js',shell.text)
            self.assertNotIn('synthetic-ui-secret',shell.text)
            self.assertNotIn('__TOKEN__',shell.text)
            self.assertEqual(client.get('/api/projects').status_code,401)
            self.assertEqual(client.get('/logis-assets/candidate_api.py').status_code,404)
            self.assertEqual(client.get('/logis-assets/canonical-ui.js').status_code,200)
        with TestClient(create_app(dsn,credentials)) as client:
            self.assertEqual(client.get('/logis').status_code,404)

    def test_task_version_conflict_and_scope_preserve_original(self):
        dsn=os.environ['LOGIS_DISPATCH_TEST_DSN'];project='ui-'+uuid.uuid4().hex
        with psycopg.connect(dsn) as c:c.execute('INSERT INTO logis_candidate.projects(id,name) VALUES(%s,%s)',(project,'UI synthetic project'))
        credentials={'synthetic-writer':{'projects':[project],'write':True},'synthetic-reader':{'projects':[],'write':False}}
        headers={'Authorization':'Bearer synthetic-writer','Idempotency-Key':uuid.uuid4().hex}
        with TestClient(create_app(dsn,credentials,original_ui=True)) as client:
            created=client.post(f'/api/projects/{project}/objects',headers=headers,json={'kind':'tasks','title':'Keep original','status':'open'}).json()
            path=f'/api/projects/{project}/objects/{created["id"]}'
            body={'title':'First edit','detail':'Checked','status':'in_progress','expected_version':1}
            first=client.patch(path,headers={**headers,'Idempotency-Key':uuid.uuid4().hex},json=body)
            self.assertEqual(first.status_code,200,first.text)
            second=client.patch(path,headers={**headers,'Idempotency-Key':uuid.uuid4().hex},json={**body,'title':'Stale edit'})
            self.assertEqual(second.status_code,409)
            rows=client.get('/api/workspace?view=tasks',headers=headers).json()
            self.assertEqual(rows[0]['title'],'First edit')
            self.assertEqual(rows[0]['version'],2)
            forbidden=client.get(f'/api/projects/{project}/dispatch',headers={'Authorization':'Bearer synthetic-reader'})
            self.assertEqual(forbidden.status_code,404)
