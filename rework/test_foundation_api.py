"""Test API integration on an isolated in-process app and synthetic project."""
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from foundation_api import register
from foundation_runtime import Foundation


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.files=root/'project'; self.files.mkdir()
        self.runtime=Foundation(root/'tasks.sqlite', lambda project:self.files)
        app=FastAPI()
        def scope(authorization:str=Header(default='')):
            if authorization not in ('Bearer write','Bearer read'):
                raise HTTPException(401,'Unauthorized')
            return {'projects':['p'],'write':authorization=='Bearer write','_dispatch_identity':{'kind':'credential','id':'synthetic-principal'}}
        def allowed(project,permissions):
            if project not in permissions['projects']:
                raise HTTPException(403,'Project denied')
        register(app,self.runtime,scope,allowed)
        self.client=TestClient(app)
        self.headers={'Authorization':'Bearer write'}

    def tearDown(self):
        self.client.close(); self.temp.cleanup()

    def test_verified_write_sequence_keeps_approval_scope_and_evidence(self):
        body={'kind':'file_write','key':'sequence','payload':{'path':'sequence.txt','content':'durable'}}
        endpoint='/api/projects/p/foundation/write_verify'
        self.assertEqual(self.client.post(endpoint,json=body,headers={'Authorization':'Bearer read'}).status_code,403)
        self.assertEqual(self.client.post(endpoint.replace('/p/','/other/'),json=body,headers=self.headers).status_code,403)
        self.assertEqual(self.client.post(endpoint,json={**body,'kind':'file_read'},headers=self.headers).status_code,409)
        response=self.client.post(endpoint,json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        pair=response.json();writer,reader=pair['write'],pair['verify']
        self.assertEqual(writer['status'],'approval');self.assertEqual(reader['status'],'waiting')
        for task in pair.values():
            self.assertNotIn('_principal',task['payload']);self.assertNotIn('token',task)
            self.assertEqual(self.runtime.ledger.get('p',task['id'])['payload']['_principal']['id'],'synthetic-principal')
        self.assertFalse(self.runtime.worker.once());self.assertFalse((self.files/'sequence.txt').exists())
        self.assertEqual(self.client.post('/api/projects/p/foundation/approve',json={'task':writer['id'],'version':writer['version']},headers=self.headers).status_code,200)
        self.assertTrue(self.runtime.worker.once());self.assertTrue(self.runtime.worker.once())
        completed=self.runtime.ledger.get('p',reader['id'])
        self.assertEqual(completed['status'],'completed');self.assertEqual(completed['result']['content'],'durable')
        self.assertEqual(completed['result']['sha256'],self.runtime.ledger.get('p',writer['id'])['artifacts'][0]['sha256'])
        replay=self.client.post(endpoint,json=body,headers=self.headers).json()
        self.assertEqual(replay['write']['id'],writer['id']);self.assertEqual(replay['verify']['id'],reader['id'])
        self.assertFalse(self.runtime.worker.once())
        changed={**body,'payload':{**body['payload'],'content':'changed'}}
        self.assertEqual(self.client.post(endpoint,json=changed,headers=self.headers).status_code,409)
        self.assertEqual((self.files/'sequence.txt').read_text(),'durable')

    def test_auth_scope_and_no_arbitrary_execution(self):
        self.assertEqual(self.client.get('/api/projects/p/foundation').status_code,401)
        self.assertEqual(self.client.get('/api/projects/other/foundation',headers=self.headers).status_code,403)
        body={'kind':'file_read','key':'read','payload':{'path':'file.txt'}}
        self.assertEqual(self.client.post('/api/projects/p/foundation/submit',json=body,headers={'Authorization':'Bearer read'}).status_code,403)
        body['kind']='shell'
        self.assertEqual(self.client.post('/api/projects/p/foundation/submit',json=body,headers=self.headers).status_code,409)

    def test_write_approval_and_evidence_over_api(self):
        body={'kind':'file_write','key':'write','payload':{'path':'out.txt','content':'hello'}}
        response=self.client.post('/api/projects/p/foundation/submit',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        task=response.json()
        self.assertEqual(task['status'],'approval')
        self.assertFalse((self.files/'out.txt').exists())
        response=self.client.post('/api/projects/p/foundation/approve',json={'task':task['id'],'version':task['version']},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.runtime.worker.once()
        response=self.client.get('/api/projects/p/foundation',params={'action':'task','task':task['id']},headers=self.headers)
        self.assertEqual(response.json()['status'],'completed',response.text)
        self.assertNotIn('_principal',response.json()['payload'])
        self.assertEqual(self.runtime.ledger.get('p',task['id'])['payload']['_principal']['id'],'synthetic-principal')
        self.assertEqual(len(response.json()['artifacts']),1)
        self.assertEqual((self.files/'out.txt').read_text(),'hello')
        response=self.client.post('/api/projects/p/foundation/submit',json=body,headers=self.headers)
        self.assertTrue(response.json()['replayed'])


if __name__=='__main__':unittest.main(verbosity=2)
