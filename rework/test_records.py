import tempfile,unittest,sqlite3
from pathlib import Path
from records import Store
class Tests(unittest.TestCase):
 def test_events_versions_and_replay(self):
  with tempfile.TemporaryDirectory() as t:
   path=Path(t)/'records.sqlite';store=Store(path)
   event=store.put('existing-task-id','task',{'title':'Original'},'request-1',project='project-1')
   self.assertEqual(event,store.put('existing-task-id','task',{'title':'Duplicate'},'request-1',project='project-1'))
   self.assertEqual(store.get('existing-task-id')['version'],1)
   with self.assertRaises(ValueError):store.put('existing-task-id','task',{},'stale',expected_version=0)
   with sqlite3.connect(path) as db:self.assertEqual(db.execute('select count(*) from events').fetchone()[0],1)
   db.close()
   store.put('existing-task-id','task',{'title':'Updated'},'request-2',expected_version=1)
   self.assertEqual(store.get('existing-task-id')['version'],2)
if __name__=='__main__':unittest.main(verbosity=2)
