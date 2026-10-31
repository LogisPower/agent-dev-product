import json,unittest
import test_local_planner as fixture
from foundation_runtime import Foundation
from local_author import LocalAuthor

class AuthorTests(unittest.TestCase):
    def setUp(self):
        fixture.LocalPlannerTests.setUp(self)
        self.foundation=Foundation(self.root.parent/'files.sqlite',lambda _:self.root,lambda _:self.allowed)
        self.author=LocalAuthor(self.loop,lambda:self.foundation)
        self.response={'path':'new.py','content':'VALUE = 1\n'}
    def tearDown(self):self.foundation.close();fixture.LocalPlannerTests.tearDown(self)
    def request(self,key='new'):return self.author.submit('p',key,'Add VALUE','new.py',['a.txt'],{'kind':'synthetic'})
    def proposal(self):
        task=self.request();self.loop.worker.once();task=self.loop.ledger.get('p',task['id']);self.assertEqual(task['status'],'completed',task);return task
    def test_review_approved_create_verify_restart_and_replay(self):
        task=self.proposal();self.assertFalse((self.root/'new.py').exists());self.assertEqual(self.transport.calls,[])
        jobs=self.author.accept('p',task['id'],task['version']);self.assertEqual(jobs['write']['status'],'approval');self.assertFalse(self.foundation.worker.once())
        self.foundation.command('p','approve',{'task':jobs['write']['id'],'version':jobs['write']['version']})
        self.foundation.close();self.foundation=Foundation(self.root.parent/'files.sqlite',lambda _:self.root,lambda _:self.allowed)
        self.assertTrue(self.foundation.worker.once());self.assertTrue(self.foundation.worker.once())
        self.assertEqual((self.root/'new.py').read_bytes(),b'VALUE = 1\n');self.assertEqual(self.author.accept('p',task['id'],task['version'])['write']['id'],jobs['write']['id'])
        self.assertEqual(self.request()['id'],task['id']);self.assertEqual(len(self.calls),1);self.assertFalse(self.loop.worker.once());self.assertFalse(self.foundation.worker.once())
        workflow=self.author.workflow('p',task['id']);self.assertEqual([x['status'] for x in workflow['tasks']],['completed','completed'])
        self.assertTrue(workflow['tasks'][0]['artifacts']);self.assertNotIn('_principal',json.dumps(workflow))
    def test_collision_after_review_never_overwrites(self):
        task=self.proposal();jobs=self.author.accept('p',task['id'],task['version']);(self.root/'new.py').write_bytes(b'keep external file')
        self.foundation.command('p','approve',{'task':jobs['write']['id'],'version':jobs['write']['version']});self.foundation.worker.once()
        self.assertEqual((self.root/'new.py').read_bytes(),b'keep external file');self.assertNotEqual(self.foundation.ledger.get('p',jobs['write']['id'])['status'],'completed')
    def test_stale_context_collision_and_revoked_scope_block_acceptance(self):
        task=self.proposal();(self.root/'a.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.author.accept('p',task['id'],task['version'])
        (self.root/'a.txt').write_bytes(b'before');(self.root/'new.py').write_bytes(b'existing')
        with self.assertRaises(ValueError):self.author.accept('p',task['id'],task['version'])
        self.allowed=False
        with self.assertRaises(PermissionError):self.author.accept('p',task['id'],task['version'])
    def test_invalid_generated_path_is_review_only(self):
        self.response['path']='other.py';task=self.request();self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review');self.assertFalse((self.root/'other.py').exists());self.assertFalse((self.root/'new.py').exists())
        self.assertFalse(self.loop.worker.once());self.assertEqual(len(self.calls),1)
    def test_bounds_missing_parent_and_writer_binding(self):
        (self.root/'new.py').write_text('existing')
        with self.assertRaises(ValueError):self.request()
        with self.assertRaises(OSError):self.author.submit('p','missing','Goal','missing/new.py',[],{'kind':'synthetic'})
        with self.assertRaises(ValueError):self.author.submit('p','outside','Goal','../new.py',[],{'kind':'synthetic'})
        self.author.foundation=lambda:None
        with self.assertRaises(ValueError):self.request()
    def test_cancellation_before_generation_has_no_effect(self):
        task=self.request();self.loop.ledger.cancel('p',task['id']);self.loop.worker.once();self.assertEqual(self.calls,[]);self.assertFalse((self.root/'new.py').exists())
    def test_invalid_content_and_during_generation_changes_hold_review(self):
        self.response['content']='x'*16001;task=self.request('oversized');self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review')
        original=self.planner.provider
        def changed(*args,**kwargs):
            value=original(*args,**kwargs);(self.root/'a.txt').write_text('concurrent');return value
        self.response['content']='VALUE = 1\n';self.planner.provider=changed;task=self.request('context-race');self.loop.worker.once()
        self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review');self.assertFalse((self.root/'new.py').exists())
    def test_writer_root_mismatch_and_duplicate_json_keys(self):
        other=self.root.parent/'other';other.mkdir();original=self.foundation.resolve_project;self.foundation.resolve_project=lambda _:other
        with self.assertRaises(PermissionError):self.request()
        self.foundation.resolve_project=original;self.planner.provider=lambda *a,**kw:'{"path":"new.py","content":"a","content":"b"}'
        task=self.request();self.loop.worker.once();self.assertEqual(self.loop.ledger.get('p',task['id'])['status'],'needs_review')
