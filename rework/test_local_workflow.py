import json,unittest
from local_planner import LocalPlanner
import test_local_work_api as fixture


class WorkflowTests(unittest.TestCase):
    setUp=fixture.LocalWorkApiTests.setUp
    tearDown=fixture.LocalWorkApiTests.tearDown
    def test_durable_goal_to_execution_recovery_and_readonly_link(self):
        calls=[]
        def provider(messages,**kwargs):
            calls.append(messages);return json.dumps({'title':'Small change','steps':[{'name':'a','path':'a.txt','old':'before','new':'after','after':[]}]})
        LocalPlanner(self.loop,provider);planning=f'/api/projects/{self.project}/local-planning'
        body={'key':'workflow','goal':'Change before to after','paths':['a.txt']}
        proposed=self.client.post(planning+'/propose',headers=self.headers,json=body)
        self.assertEqual(proposed.status_code,200,proposed.text);proposal=proposed.json()
        status=self.base+'?action=workflow&task='+proposal['id']
        self.assertEqual(self.client.get(status,headers=self.headers).json()['phase'],'planning_queued')
        self.loop.worker.once();current=self.loop.ledger.get(self.project,proposal['id'])
        self.assertEqual(self.client.get(status,headers=self.headers).json()['phase'],'proposal_ready')
        decision={'task':proposal['id'],'version':current['version']}
        plan=self.client.post(planning+'/accept',headers=self.headers,json=decision).json();child=plan['tasks'][0]
        self.assertEqual(self.client.get(status,headers=self.headers).json()['phase'],'awaiting_approval')
        self.assertFalse(self.loop.worker.once())
        self.client.post(self.base+'/approve',headers=self.headers,json={'task':child['id'],'version':child['version']})
        self.provider.uncertain=True;self.loop.worker.once()
        state=self.client.get(status,headers=self.headers).json();self.assertEqual(state['phase'],'execution_review')
        self.assertEqual((self.root/'a.txt').read_bytes(),b'after')
        self.assertFalse(self.loop.worker.once());self.assertEqual(len(self.provider.calls),1)
        uncertain=state['tasks'][0]
        accepted=self.client.post(self.base+'/reconcile',headers=self.headers,json={'task':uncertain['id'],'version':uncertain['version']})
        self.assertEqual(accepted.status_code,200,accepted.text)
        final=self.client.get(status,headers={'Authorization':'Bearer reader'})
        self.assertEqual(final.json()['phase'],'completed');self.assertTrue(final.json()['read_only']);self.assertFalse(final.json()['automatic_retry'])
        self.assertEqual(self.client.get(status,headers={'Authorization':'Bearer outsider'}).status_code,404)
        self.client.post(planning+'/propose',headers=self.headers,json=body)
        self.client.post(planning+'/accept',headers=self.headers,json=decision)
        self.assertFalse(self.loop.worker.once());self.assertEqual(len(calls),1);self.assertEqual(len(self.provider.calls),1)
        for hidden in ('_principal','_root','"token"'):self.assertNotIn(hidden,final.text)
