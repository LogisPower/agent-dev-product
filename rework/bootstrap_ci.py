import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
import psycopg
with psycopg.connect(os.environ['LOGIS_TEST_DSN']) as db:
    directory=db.execute('SHOW data_directory').fetchone()[0]
    if '/rework/postgres-restore-' not in directory.replace('\\','/').lower():raise RuntimeError('CI requires isolated PostgreSQL data directory')
    for filename in ['001_canonical.sql','002_delivery.sql','003_event_feed.sql']:db.execute((Path(__file__).parent/filename).read_text())
    for identifier in ['ci-project-a','ci-project-b']:
        db.execute("INSERT INTO logis_candidate.projects(id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING",(identifier,identifier))
print('Synthetic CI database ready; no production data imported')
