import json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import test_local_planner as fixture
from project_verification import ProjectVerification
from local_work_loop import LocalWorkLoop
from source_validation import validate_source

class VerificationTests(unittest.TestCase):
    setUp=fixture.LocalPlannerTests.setUp
    tearDown=fixture.LocalPlannerTests.tearDown
    def set_files(self):
        (self.root/'a.js').write_text('export const answer = 42;')
        (self.root/'b.ts').write_text('export const answer: number = 42;')
        self.verification=ProjectVerification(self.loop)
    def request(self,key='verify'):return self.verification.submit('p',key,['a.js','b.ts'],{'kind':'synthetic'})
    def test_durable_report_restart_replay_and_explicit_fresh_check(self):
        self.set_files();task=self.request();self.loop.close()
        self.loop=LocalWorkLoop(self.root.parent/'jobs.sqlite',lambda _:self.root,lambda _:self.allowed,self.transport);self.verification=ProjectVerification(self.loop)
        self.loop.worker.once();state=self.loop.ledger.get('p',task['id']);self.assertEqual(state['status'],'completed',state)
        self.assertTrue(state['result']['passed']);self.assertFalse(state['result']['semantic_tests_run']);self.assertEqual(self.calls,[]);self.assertEqual(self.transport.calls,[])
        (self.root/'a.js').write_text('export const broken = ;');self.assertEqual(self.request()['id'],task['id']);self.assertFalse(self.loop.worker.once())
        fresh=self.request('fresh');self.loop.worker.once();state=self.loop.ledger.get('p',fresh['id']);self.assertEqual(state['status'],'completed');self.assertFalse(state['result']['passed'])
    def test_stale_snapshot_scope_cancel_and_missing(self):
        self.set_files();task=self.request();(self.root/'b.ts').write_text('changed')
        self.loop.worker.once();self.assertNotEqual(self.loop.ledger.get('p',task['id'])['status'],'completed')
        with self.assertRaises(OSError):self.verification.submit('p','missing',['missing.ts'],{'kind':'synthetic'})
        task=self.request('cancel');self.loop.ledger.cancel('p',task['id']);self.loop.worker.once();self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'canceled')
        self.allowed=False
        with self.assertRaises(PermissionError):self.request('denied')
    def test_change_during_check_withholds_completed_report(self):
        self.set_files();task=self.request();original=validate_source
        def changed(path,content):
            value=original(path,content);(self.root/'a.js').write_text('concurrent');return value
        with patch('project_verification.validate_source',changed):self.loop.worker.once()
        self.assertNotEqual(self.loop.ledger.get('p',task['id'])['status'],'completed')
    def test_unsupported_and_size_bounds(self):
        self.set_files();(self.root/'x.tsx').write_text('const x = <div/>')
        task=self.verification.submit('p','tsx',['x.tsx'],{'kind':'synthetic'});self.loop.worker.once();result=self.loop.ledger.get('p',task['id'])['result']
        self.assertFalse(result['passed']);self.assertEqual(result['checks'][0]['status'],'unsupported')
        (self.root/'a.js').write_text('x'*65537)
        with self.assertRaises(ValueError):self.request()

class JavaScriptTests(unittest.TestCase):
    def test_real_parsers_accept_and_reject_without_execution_or_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            sentinel=Path(folder)/'never-created';path=json.dumps(str(sentinel))
            source="require('node:fs').writeFileSync("+path+",'executed'); throw Error('runtime only');"
            self.assertEqual(validate_source('danger.cjs',source)['status'],'passed');self.assertFalse(sentinel.exists())
            for name,source in [('x.js',"import missing from './absent.js'; export const x=1;"),('x.ts','enum Color { Red, Blue }; export const x: Color = Color.Red;'),('x.cts','const x: number = 1; module.exports=x;'),('x.mts','export type Item = {x:number};')]:
                value=validate_source(name,source);self.assertEqual(value['status'],'passed',value);self.assertFalse(value['type_checking']);self.assertFalse(value['imports_resolved'])
            for name,source in [('x.js','const = ;'),('x.ts','const x: = 1;'),('x.mjs','return 1;')]:self.assertEqual(validate_source(name,source)['status'],'failed')
            self.assertEqual(validate_source('x.ts','const x: number = "type error deliberately not checked";')['status'],'passed')
            self.assertEqual(validate_source('x.tsx','const x=<div/>')['status'],'unsupported')
    def test_missing_runtime_and_timeout_fail_closed(self):
        from javascript_validation import NODE
        with patch('javascript_validation.NODE',Path('missing-runtime.exe')):self.assertEqual(validate_source('x.js','let x=1')['status'],'unavailable')
        import subprocess
        with patch('javascript_validation.subprocess.run',side_effect=subprocess.TimeoutExpired('node',3)) as run:
            self.assertEqual(validate_source('x.js','let x=1')['status'],'unavailable')
            args,kw=run.call_args;self.assertEqual(args[0][0],str(NODE));self.assertNotIn('NODE_OPTIONS',kw['env']);self.assertNotIn('shell',kw)
