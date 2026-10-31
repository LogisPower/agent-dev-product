"""Offline acceptance tests: synthetic state only, no resident model or live data."""
import concurrent.futures
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from durable_tasks import Ledger, Conflict
from task_worker import Worker, FILE_HANDLERS, Retryable
from project_files import ProjectFiles
from foundation_runtime import Foundation


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files_root = self.root / 'project'
        self.files_root.mkdir()
        (self.files_root / '.logis').mkdir()
        self.db = self.root / 'tasks.sqlite'
        self.ledger = Ledger(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def task(self, key='key', **kwargs):
        return self.ledger.submit('p', key, 'test', {'request': key}, **kwargs)


class QueueTests(Fixture):
    def test_verified_write_atomic_idempotency_and_recovery(self):
        payload={'path':'out.txt','content':'hello','_principal':{'id':'owner'}}
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            pairs=list(pool.map(lambda _:self.ledger.submit_verified_write('p','flow',payload),range(4)))
        writer,reader=pairs[0]['write'],pairs[0]['verify']
        self.assertTrue(all(pair['write']['id']==writer['id'] and pair['verify']['id']==reader['id'] for pair in pairs))
        self.assertEqual(writer['status'],'approval');self.assertEqual(reader['status'],'waiting')
        self.assertEqual(reader['payload']['_principal'],payload['_principal'])
        self.assertIsNone(self.ledger.claim('worker'))
        restarted=Ledger(self.db)
        self.assertEqual(restarted.submit_verified_write('p','flow',payload)['verify']['id'],reader['id'])
        restarted.approve('p',writer['id'],writer['version'])
        active=restarted.claim('worker');self.assertEqual(active['id'],writer['id'])
        restarted.recover(exclusive_restart=True)
        self.assertEqual(restarted.get('p',writer['id'])['status'],'needs_review')
        self.assertIsNone(restarted.claim('worker'))
        self.assertEqual(restarted.get('p',reader['id'])['status'],'waiting')
        with self.assertRaises(Conflict):
            restarted.submit_verified_write('p','flow',{**payload,'content':'different'})

    def test_verified_write_capacity_rolls_back_both_jobs(self):
        for index in range(127):self.task(str(index))
        with self.assertRaises(Conflict):
            self.ledger.submit_verified_write('p','flow',{'path':'out.txt','content':'hello'})
        with self.ledger.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],127)
            self.assertEqual(c.execute('SELECT count(*) FROM task_events').fetchone()[0],127)
            self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE request_key LIKE 'flow:%'").fetchone()[0],0)

    def test_verified_write_second_key_conflict_rolls_back_writer(self):
        self.task('flow:verify')
        with self.assertRaises(Conflict):
            self.ledger.submit_verified_write('p','flow',{'path':'out.txt','content':'hello'})
        with self.ledger.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM task_events').fetchone()[0],1)

    def test_terminal_writer_closes_unstarted_verification_once(self):
        for terminal in ('canceled','failed'):
            with self.subTest(terminal=terminal):
                ledger=Ledger(self.root/(terminal+'.sqlite'))
                flow=ledger.submit_verified_write('p','flow',{'path':'out.txt','content':'hello'})
                writer,reader=flow['write'],flow['verify']
                if terminal=='canceled':ledger.cancel('p',writer['id'])
                else:
                    ledger.approve('p',writer['id'],writer['version'])
                    attempt=ledger.claim('worker')
                    ledger.finish(attempt['id'],attempt['token'],'failed',{'effect_started':False})
                self.assertIsNone(ledger.claim('worker'))
                stopped=ledger.get('p',reader['id'])
                self.assertEqual(stopped['status'],'canceled')
                self.assertEqual(stopped['attempts'],0);self.assertEqual(stopped['artifacts'],[])
                self.assertEqual(stopped['result']['reason'],'Dependency cannot produce committed artifact')
                self.assertEqual(stopped['result']['blocked_by'],[{'task':writer['id'],'status':terminal}])
                cursor=ledger.list('p')['next_cursor']
                self.assertIsNone(ledger.claim('worker'))
                self.assertEqual(ledger.list('p',after=cursor)['events'],[])
                next_job=ledger.submit('p','unrelated','test',{})
                self.assertEqual(ledger.claim('worker')['id'],next_job['id'])

    def test_idempotency_conflict_and_restart(self):
        first = self.task()
        self.assertEqual(Ledger(self.db).submit('p', 'key', 'test', {'request': 'key'})['id'], first['id'])
        with self.assertRaises(Conflict):
            self.ledger.submit('p', 'key', 'test', {'request': 'changed'})
        with self.assertRaises(KeyError):
            self.ledger.get('other', first['id'])

    def test_single_claim_under_concurrency(self):
        self.task('a'); self.task('b')
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            claims = list(pool.map(lambda n: self.ledger.claim(str(n)), range(8)))
        self.assertEqual(sum(x is not None for x in claims), 1)

    def test_bounded_retries(self):
        clock = [100.0]
        self.ledger.clock = lambda: clock[0]
        job = self.task()
        for n in range(3):
            attempt = self.ledger.claim('worker')
            self.assertEqual(attempt['attempts'], n + 1)
            self.ledger.retry(attempt['id'], attempt['token'], 'safe pre-effect failure')
            clock[0] += 61
        self.assertEqual(self.ledger.get('p', job['id'])['status'], 'failed')
        self.assertIsNone(self.ledger.claim('worker'))

    def test_dependency_requires_evidence(self):
        creator = self.task('creator', outputs=['a.txt'])
        child = self.task('child', dependencies=[{'task': creator['id'], 'path': 'a.txt'}])
        run = self.ledger.claim('worker')
        with self.assertRaises(ValueError):
            self.ledger.finish(run['id'], run['token'], 'completed', {}, [])
        self.assertIsNone(self.ledger.claim('second'))
        self.ledger.finish(run['id'], run['token'], 'completed', {}, [{'path': 'a.txt', 'sha256': 'a' * 64}])
        self.assertEqual(self.ledger.claim('worker')['id'], child['id'])

    def test_unknown_creator_and_cross_project_rejected(self):
        creator = self.task(outputs=['x'])
        with self.assertRaises(ValueError):
            self.ledger.submit('other', 'child', 'test', {}, dependencies=[{'task': creator['id'], 'path': 'x'}])
        with self.assertRaises(ValueError):
            self.task('unknown', dependencies=[{'task': 'absent', 'path': 'x'}])

    def test_cancel_before_and_during_work(self):
        first = self.task('first')
        self.assertEqual(self.ledger.cancel('p', first['id'])['status'], 'canceled')
        self.assertIsNone(self.ledger.claim('w'))
        second = self.task('second')
        run = self.ledger.claim('w')
        self.ledger.cancel('p', second['id'])
        self.assertTrue(self.ledger.heartbeat(run['id'], run['token']))
        self.ledger.finish(run['id'], run['token'], 'completed', {'late_reply': True})
        self.assertEqual(self.ledger.get('p', second['id'])['status'], 'canceled')

    def test_recovery_fences_old_attempt_and_preserves_checkpoint(self):
        job = self.task(outputs=['x'])
        run = self.ledger.claim('w')
        self.ledger.heartbeat(run['id'], run['token'], {'phase': 'write', 'receipt': job['id']})
        self.assertEqual(Ledger(self.db).recover(exclusive_restart=True), 1)
        with self.assertRaises(Conflict):
            self.ledger.finish(run['id'], run['token'], 'completed', {})
        restored = self.ledger.get('p', job['id'])
        self.assertEqual(restored['status'], 'needs_review')
        self.assertEqual(restored['checkpoint']['receipt'], job['id'])
        self.task('competing', outputs=['x'])
        self.assertIsNone(self.ledger.claim('w'))

    def test_real_process_crash_does_not_replay(self):
        self.task()
        marker = self.root / 'claimed'
        code = "from durable_tasks import Ledger; from pathlib import Path; import time,sys; q=Ledger(sys.argv[1]); a=q.claim('child'); q.heartbeat(a['id'],a['token'],{'step':1}); Path(sys.argv[2]).write_text(a['id']); time.sleep(30)"
        child = subprocess.Popen([sys.executable, '-c', code, str(self.db), str(marker)], cwd=Path(__file__).parent)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists())
        finally:
            child.terminate(); child.wait(timeout=5)
        restarted = Ledger(self.db)
        restarted.recover(exclusive_restart=True)
        task = restarted.get('p', marker.read_text())
        self.assertEqual(task['checkpoint'], {'step': 1})
        self.assertEqual(task['status'], 'needs_review')
        self.assertIsNone(restarted.claim('new'))

    def test_event_paging_no_loss(self):
        for i in range(5):
            self.task(str(i))
        seen, cursor = [], 0
        while True:
            page = self.ledger.list('p', cursor, 2)
            seen.extend(e['sequence'] for e in page['events'])
            cursor = page['next_cursor']
            if not page['has_more']:
                break
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)

    def test_cancel_during_effect_requires_review(self):
        task=self.task(outputs=['out'])
        run=self.ledger.claim('w')
        self.ledger.cancel('p',task['id'])
        self.ledger.finish(run['id'],run['token'],'completed',{'effect_started':True},[{'path':'out','sha256':'a'*64}])
        self.assertEqual(self.ledger.get('p',task['id'])['status'],'needs_review')

    def test_scope_revoked_before_dispatch(self):
        task=self.task()
        called=[]
        worker=Worker(self.ledger,{'test':lambda *args:called.append(1)},lambda p:None,lambda t:False)
        worker.once()
        self.assertEqual(called,[])
        self.assertEqual(self.ledger.get('p',task['id'])['status'],'failed')


@unittest.skipUnless(os.name == 'nt', 'Pinned Windows file adapter')
class FileTests(Fixture):
    def test_invalid_read_jobs_rejected_before_queue_admission(self):
        from foundation_runtime import Foundation
        runtime=Foundation(self.db,lambda _:self.files_root)
        for fields in ({'offset':True},{'offset':-1},{'offset':131073},{'limit':0},{'limit':32769},{'limit':False},
                       {'expected_sha256':5},{'expected_sha256':'bad'},{'offset':1}):
            with self.assertRaises(ValueError):
                runtime.command('p','submit',{'key':'invalid','kind':'file_read','payload':{'path':'a.txt',**fields}})
        self.assertEqual(runtime.query('p')['tasks'],[])
        valid=runtime.command('p','submit',{'key':'valid','kind':'file_read','payload':{'path':'a.txt','offset':1,'limit':1,'expected_sha256':'a'*64}})
        self.assertEqual(valid['kind'],'file_read');runtime.close()

    def setUp(self):
        super().setUp()
        self.files = ProjectFiles(self.files_root, '/workspace/project')

    def test_mapping_traversal_and_missing(self):
        self.assertEqual(self.files.relative(str(self.files_root / 'a.txt')), 'a.txt')
        self.assertEqual(self.files.relative('/workspace/project/a.txt'), 'a.txt')
        for path in ('/a.txt', '../a.txt', '/workspace/project-other/a.txt', '.env', 'CON.txt', 'x/../a'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.files.relative(path)
        self.assertEqual(self.files.read('missing.txt')['status'], 'missing')

    def test_read_bound_and_current_version(self):
        (self.files_root / 'a.txt').write_text('abcdef', encoding='utf-8')
        first = self.files.read('a.txt', limit=2)
        self.assertEqual(first['content'], 'ab')
        self.assertEqual(self.files.read('a.txt', offset=2, expected_sha256=first['sha256'])['content'], 'cdef')
        (self.files_root / 'a.txt').write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.files.read('a.txt', offset=2, expected_sha256=first['sha256'])
        (self.files_root / 'large.txt').write_bytes(b'a' * 131073)
        with self.assertRaises(ValueError):
            self.files.read('large.txt')

    def test_continuation_requires_file_version(self):
        path = self.files_root / 'a.txt'
        path.write_text('abcdef', encoding='utf-8')
        first = self.files.read('a.txt', limit=2)
        path.write_text('UVWXYZ', encoding='utf-8')
        for version in (None, ''):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'expected_sha256'):
                self.files.read('a.txt', offset=2, expected_sha256=version)
        with self.assertRaisesRegex(ValueError, 'changed between pages'):
            self.files.read('a.txt', offset=2, expected_sha256=first['sha256'])
        restarted = self.files.read('a.txt', limit=2)
        self.assertEqual(restarted['content'], 'UV')
        self.assertEqual(self.files.read('a.txt', offset=2, expected_sha256=restarted['sha256'])['content'], 'WXYZ')

    def test_listing_version_and_search(self):
        for i in range(4):
            (self.files_root / f'{i}.txt').write_text('needle' if i == 2 else 'hay')
        page = self.files.listing(limit=2)
        self.assertEqual(len(self.files.listing(cursor=page['next_cursor'], limit=2)['entries']), 2)
        self.assertEqual(self.files.search('needle', content=True)['matches'][0]['path'], '2.txt')
        (self.files_root / 'new.txt').write_text('new')
        with self.assertRaises(ValueError):
            self.files.listing(cursor=page['next_cursor'])

    def test_search_exact_limit_with_later_nonmatches(self):
        (self.files_root / 'a-needle.txt').write_text('hay')
        (self.files_root / 'z.txt').write_text('hay')
        result = self.files.search('needle', limit=1)
        self.assertEqual([row['path'] for row in result['matches']], ['a-needle.txt'])
        self.assertIsNone(result['next_cursor'])
        (self.files_root / 'b-needle.txt').write_text('hay')
        with self.assertRaisesRegex(ValueError, 'Too many matches'):
            self.files.search('needle', limit=1)
        self.assertEqual(len(self.files.search('needle', limit=2)['matches']), 2)

    def test_content_search_limit_preserves_skips_and_overflow(self):
        (self.files_root / 'a.txt').write_text('needle')
        (self.files_root / 'b.txt').write_text('hay')
        (self.files_root / 'z.txt').write_bytes(b'x' * 131073)
        result = self.files.search('needle', content=True, limit=1)
        self.assertEqual([row['path'] for row in result['matches']], ['a.txt'])
        self.assertEqual(result['skipped'], [{'path': 'z.txt', 'reason': 'file exceeds read bound'}])
        (self.files_root / 'b.txt').write_text('needle')
        with self.assertRaisesRegex(ValueError, 'Too many matches'):
            self.files.search('needle', content=True, limit=1)
        self.assertEqual(len(self.files.search('needle', content=True, limit=2)['matches']), 2)

    def test_write_replay_and_stale_no_loss(self):
        first = self.files.write('a.txt', 'original', 'a' * 32)
        self.assertTrue(self.files.write('a.txt', 'original', 'a' * 32)['receipt']['replayed'])
        self.files.write('a.txt', 'updated', 'b' * 32, first['artifact']['sha256'])
        with self.assertRaises(ValueError):
            self.files.write('a.txt', 'stale replacement', 'c' * 32, first['artifact']['sha256'])
        self.assertEqual(self.files.read('a.txt')['content'], 'updated')
        self.assertEqual((self.files_root / '.logis' / ('b' * 32 + '.before')).read_text(), 'original')
        self.assertTrue(self.files.workspace.inspect('b' * 32)['original_recovery_verified'])

    def test_concurrent_edits_only_one_wins(self):
        initial = self.files.write('a.txt', 'initial', 'd' * 32)
        def write(n):
            try:
                return ProjectFiles(self.files_root).write('a.txt', str(n), str(n) * 32, initial['artifact']['sha256'])
            except (ValueError, OSError):
                return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(write, (1, 2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertIn(self.files.read('a.txt')['content'], ('1', '2'))

    def test_queue_worker_approval_artifact_dependency_end_to_end(self):
        runtime = Foundation(self.db, lambda project: self.files_root)
        writer = runtime.command('p', 'submit', {'key': 'write', 'kind': 'file_write', 'payload': {'path': 'result.txt', 'content': 'saved'}})
        reader = runtime.command('p', 'submit', {'key': 'read', 'kind': 'file_read', 'payload': {'path': 'result.txt'}, 'dependencies': [{'task': writer['id'], 'path': 'result.txt'}]})
        self.assertFalse(runtime.worker.once())
        runtime.command('p', 'approve', {'task': writer['id'], 'version': writer['version']})
        self.assertTrue(runtime.worker.once()); self.assertTrue(runtime.worker.once())
        done = runtime.ledger.get('p', reader['id'])
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['result']['content'], 'saved')
        self.assertEqual(runtime.ledger.get('p', writer['id'])['artifacts'][0]['sha256'], hashlib.sha256(b'saved').hexdigest())

    def test_changed_artifact_blocks_dependent(self):
        runtime = Foundation(self.db, lambda project: self.files_root)
        writer = runtime.command('p', 'submit', {'key': 'w', 'kind': 'file_write', 'payload': {'path': 'out.txt', 'content': 'original'}})
        reader = runtime.command('p', 'submit', {'key': 'r', 'kind': 'file_read', 'payload': {'path': 'out.txt'}, 'dependencies': [{'task': writer['id'], 'path': 'out.txt'}]})
        runtime.command('p', 'approve', {'task': writer['id'], 'version': writer['version']})
        runtime.worker.once()
        (self.files_root / 'out.txt').write_text('tampered')
        runtime.worker.once()
        self.assertEqual(runtime.ledger.get('p', reader['id'])['status'], 'failed')

    def test_dependent_read_is_pinned_even_if_file_changes_after_dependency_check(self):
        from unittest.mock import patch
        runtime=Foundation(self.db,lambda _:self.files_root)
        writer=runtime.command('p','submit',{'key':'creator','kind':'file_write','payload':{'path':'out.txt','content':'original'}})
        reader=runtime.command('p','submit',{'key':'verify','kind':'file_read','payload':{'path':'out.txt'},'dependencies':[{'task':writer['id'],'path':'out.txt'}]})
        runtime.command('p','approve',{'task':writer['id'],'version':writer['version']});runtime.worker.once()
        original=ProjectFiles.verify
        def change_after_check(files,path,sha):
            result=original(files,path,sha);(self.files_root/path).write_text('changed after check');return result
        with patch.object(ProjectFiles,'verify',change_after_check):runtime.worker.once()
        self.assertEqual(runtime.ledger.get('p',reader['id'])['status'],'failed')

    def test_creator_cancel_updates_waiting_dependency_evidence(self):
        runtime=Foundation(self.db,lambda _:self.files_root)
        writer=runtime.command('p','submit',{'key':'creator','kind':'file_write','payload':{'path':'out.txt','content':'original'}})
        reader=runtime.command('p','submit',{'key':'verify','kind':'file_read','payload':{'path':'out.txt'},'dependencies':[{'task':writer['id'],'path':'out.txt'}]})
        cursor=runtime.query('p')['next_cursor'];runtime.command('p','cancel',{'task':writer['id']})
        page=runtime.query('p',after=cursor);waiting=next(t for t in page['tasks'] if t['id']==reader['id'])
        self.assertEqual(waiting['dependencies'][0]['status'],'canceled');self.assertFalse(runtime.worker.once())

    def test_effect_commit_then_process_loss_reconciles_without_rewrite(self):
        runtime=Foundation(self.db,lambda p:self.files_root)
        task=runtime.command('p','submit',{'key':'recover','kind':'file_write','payload':{'path':'out.txt','content':'verified'}})
        runtime.command('p','approve',{'task':task['id'],'version':task['version']})
        claimed=runtime.ledger.claim('old')
        self.files.write('out.txt','verified',task['id'])
        runtime.ledger.recover(exclusive_restart=True)
        pending=runtime.ledger.get('p',task['id'])
        before=(self.files_root/'out.txt').stat().st_mtime_ns
        done=runtime.command('p','reconcile',{'task':task['id'],'version':pending['version']})
        self.assertEqual(done['status'],'completed')
        self.assertFalse(done['result']['reexecuted'])
        self.assertEqual((self.files_root/'out.txt').stat().st_mtime_ns,before)

    def test_shared_agent_discovery_and_paging(self):
        from unittest.mock import patch
        from intent_core import Action,Plan,validate
        from workspace_facade import execute
        (self.files_root/'visible.txt').write_text('a'*13000)
        with patch('workspace_facade.workspace',return_value=self.files.workspace):
            listing=execute(None,'p',Action(tool='workspace_list'),{'projects':['p']},'run')
            self.assertEqual(listing['entries'][0]['path'],'visible.txt')
            action=Action(tool='workspace_read',path='visible.txt')
            validate(Plan(actions=[action]),'read visible.txt')
            first=execute(None,'p',action,{'projects':['p']},'run')
            self.assertEqual(first['next_offset'],12000)
            second=execute(None,'p',Action(tool='workspace_read',path='visible.txt',offset=12000,expected_sha256=first['sha256']),{'projects':['p']},'run')
            self.assertEqual(len(second['content']),1000)


class TransportTests(unittest.TestCase):
    def test_cancel_closes_actual_http_socket(self):
        from chat_transport import completion
        from provider_cancel import ProviderCanceled
        started, disconnected, canceled = threading.Event(), threading.Event(), threading.Event()
        class Provider(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                self.wfile.flush(); started.set()
                self.connection.settimeout(3)
                try:
                    if self.connection.recv(1) == b'':
                        disconnected.set()
                except (ConnectionResetError, ConnectionAbortedError):
                    disconnected.set()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True); server_thread.start()
        errors = []
        def request():
            try:
                completion([{'role': 'user', 'content': 'test'}], timeout=5, port=server.server_port, canceled=canceled.is_set)
            except Exception as error:
                errors.append(error)
        caller = threading.Thread(target=request); caller.start()
        try:
            self.assertTrue(started.wait(2))
            canceled.set(); caller.join(2)
            self.assertFalse(caller.is_alive())
            self.assertTrue(disconnected.wait(1))
            self.assertIsInstance(errors[0], ProviderCanceled)
        finally:
            canceled.set(); caller.join(6); server.shutdown(); server.server_close(); server_thread.join(2)


class ContextTests(Fixture):
    def test_compaction_is_bounded_across_reentry(self):
        from context_guard import ContextGuard
        self.task(); task = self.ledger.claim('w')
        guard = ContextGuard(self.ledger, task['id'], task['token'], lambda payload: len(json.dumps(payload)), 150, 10)
        calls = []
        messages = [{'role': 'system', 'content': 'authority'}, {'role': 'user', 'content': 'x' * 1000}]
        original = json.dumps(messages)
        def empty(value):
            calls.append(1); return ''
        for _ in range(3):
            with self.assertRaises(ValueError):
                guard.fit(messages, [], empty)
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.dumps(messages), original)
        self.ledger.heartbeat(task['id'],task['token'],{'unrelated_checkpoint':True})
        with self.assertRaises(ValueError):guard.fit(messages,[],empty)
        self.assertEqual(len(calls),2)
        with self.ledger.connection() as c:
            saved=c.execute('SELECT original FROM task_contexts WHERE job=?',(task['id'],)).fetchone()[0]
        self.assertEqual(json.loads(saved)['messages'],messages)


if __name__ == '__main__':
    unittest.main(verbosity=2)
