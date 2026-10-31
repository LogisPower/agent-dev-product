import json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import test_local_author as fixture
from local_mixed_plan import MixedPlans
from source_validation import validate_source
from foundation_runtime import Foundation

class MixedTests(unittest.TestCase):
    setUp=fixture.AuthorTests.setUp
    tearDown=fixture.AuthorTests.tearDown
    def proposals(self):
        (self.root/'existing.py').write_text('VALUE = 0\n')
        new=self.author.submit('p','new','Create module','new.py',[],{'kind':'synthetic'});self.loop.worker.once()
        self.response={'title':'Update','steps':[{'name':'update','path':'existing.py','old':'VALUE = 0','new':'VALUE = 2','after':[]}]}
        edit=self.planner.submit('p','edit','Update module',['existing.py'],{'kind':'synthetic'});self.loop.worker.once()
        self.mixed=MixedPlans(self.loop,self.author)
        return [{'task':task['id'],'version':self.loop.ledger.get('p',task['id'])['version']} for task in (new,edit)]
    def submit(self,selections,key='mixed',**kwargs):return self.mixed.submit('p',key,'Create and edit',selections,{'kind':'synthetic'},**kwargs)
    def test_mixed_approval_dependency_restart_replay_and_claims(self):
        selections=self.proposals();result=self.submit(selections);self.assertEqual(len(result['tasks']),4)
        self.assertEqual([s['operation'] for s in result['steps']],['create','edit']);self.assertTrue(all(s['validation']['status']=='passed' for s in result['steps']))
        self.assertFalse(self.foundation.worker.once());self.assertFalse((self.root/'new.py').exists())
        for task in result['tasks']:
            if task['kind']=='file_write':self.foundation.command('p','approve',{'task':task['id'],'version':task['version']})
        self.foundation.worker.once();self.assertEqual((self.root/'existing.py').read_text(),'VALUE = 0\n')
        self.foundation.close();self.foundation=Foundation(self.root.parent/'files.sqlite',lambda _:self.root,lambda _:self.allowed)
        for _ in range(4):self.foundation.worker.once()
        self.assertEqual((self.root/'new.py').read_text(),'VALUE = 1\n');self.assertEqual((self.root/'existing.py').read_text(),'VALUE = 2\n')
        self.assertEqual(self.submit(selections)['id'],result['id']);self.assertFalse(self.foundation.worker.once());self.assertEqual(len(self.calls),2)
        with self.assertRaises(ValueError):self.author.accept('p',**{'task_id':selections[0]['task'],'version':selections[0]['version']})
        with self.assertRaises(ValueError):self.planner.accept('p',selections[1]['task'],selections[1]['version'])
        saved=self.mixed.list('p',{'kind':'synthetic'});self.assertNotIn('"root"',json.dumps(saved));self.assertTrue(all(t['status']=='completed' for t in saved['plans'][0]['tasks']))
    def test_atomic_admission_rollback(self):
        selections=self.proposals();original=self.foundation.ledger.submit_verified_write;calls=[]
        def fail(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise ValueError('injected admission failure')
            return original(*args,**kwargs)
        with patch.object(self.foundation.ledger,'submit_verified_write',fail):
            with self.assertRaisesRegex(ValueError,'injected'):self.submit(selections)
        with self.foundation.ledger.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(len(self.submit(selections)['tasks']),4)
    def test_changed_dependency_holds_later_edit_without_loss(self):
        result=self.submit(self.proposals())
        for task in result['tasks']:
            if task['kind']=='file_write':self.foundation.command('p','approve',{'task':task['id'],'version':task['version']})
        self.foundation.worker.once();(self.root/'new.py').write_text('external version')
        for _ in range(4):self.foundation.worker.once()
        self.assertEqual((self.root/'existing.py').read_text(),'VALUE = 0\n')
    def test_stale_selection_and_changed_contract_reject(self):
        selections=self.proposals();(self.root/'existing.py').write_text('external')
        with self.assertRaises(ValueError):self.submit(selections)
        (self.root/'existing.py').write_text('VALUE = 0\n');self.submit(selections)
        with self.assertRaises(ValueError):self.mixed.submit('p','mixed','Different title',selections,{'kind':'synthetic'})

    def test_unsupported_acknowledgement_and_invalid_syntax_gate(self):
        self.response={'path':'notes.txt','content':'review me'}
        task=self.author.submit('p','notes','Notes','notes.txt',[],{'kind':'synthetic'});self.loop.worker.once()
        self.mixed=MixedPlans(self.loop,self.author);selections=[{'task':task['id'],'version':self.loop.ledger.get('p',task['id'])['version']}]
        with self.assertRaisesRegex(ValueError,'Unsupported'):self.submit(selections)
        result=self.submit(selections,allow_unsupported=True);self.assertEqual(result['steps'][0]['validation']['status'],'unsupported')
        self.response={'path':'invalid.py','content':'return 42'}
        task=self.author.submit('p','invalid','Invalid','invalid.py',[],{'kind':'synthetic'});self.loop.worker.once()
        selections=[{'task':task['id'],'version':self.loop.ledger.get('p',task['id'])['version']}]
        with self.assertRaisesRegex(ValueError,'validation failed'):self.submit(selections,key='invalid',allow_unsupported=True)
        self.assertFalse((self.root/'invalid.py').exists())

class ValidationTests(unittest.TestCase):
    def test_parse_never_runs_generated_code(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'should-not-exist'
            source='from pathlib import Path\nPath('+repr(str(target))+').write_text("executed")\n'
            value=validate_source('test.py',source);self.assertEqual(value['status'],'passed');self.assertFalse(target.exists());self.assertFalse(value['generated_code_executed'])
        self.assertEqual(validate_source('bad.py','def broken(:')['status'],'failed')
        self.assertEqual(validate_source('good.json','{"a":1}')['status'],'passed')
        self.assertEqual(validate_source('bad.json','{bad}')['status'],'failed')
        self.assertEqual(validate_source('bad.json','NaN')['status'],'failed')
        self.assertEqual(validate_source('bad.py','return 42')['status'],'failed')
        self.assertEqual(validate_source('module.js','throw new Error()')['status'],'passed')
    def test_bounds_timeout_and_fixed_command(self):
        with self.assertRaises(ValueError):validate_source('big.py','x'*65537)
        import subprocess
        with patch('source_validation.subprocess.run',side_effect=subprocess.TimeoutExpired('parser',3)) as run:
            value=validate_source('x.py','print("no")');self.assertEqual(value['status'],'unavailable')
            args,kwargs=run.call_args;self.assertEqual(args[0][1:3],['-I','-S']);self.assertEqual(kwargs['timeout'],3);self.assertNotIn('shell',kwargs);self.assertNotIn('PATH',kwargs['env'])
