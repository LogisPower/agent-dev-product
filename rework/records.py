"""Candidate canonical store. Isolated from the production app during migration."""
import json,sqlite3,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
class Store:
    def __init__(self,path):
        self.path=path
        with self.transaction() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,kind TEXT NOT NULL,project_id TEXT,payload TEXT NOT NULL,version INTEGER NOT NULL);CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,object_id TEXT NOT NULL,actor_id TEXT NOT NULL,timestamp TEXT NOT NULL,correlation_id TEXT NOT NULL,schema_version INTEGER NOT NULL,permissions_scope TEXT NOT NULL,payload TEXT NOT NULL,delivered INTEGER DEFAULT 0);CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY,event_id TEXT NOT NULL);""")
    @contextmanager
    def transaction(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
    def put(self,identifier,kind,payload,operation_key,actor='user',project=None,expected_version=None):
        with self.transaction() as db:
            old=db.execute('select event_id from operations where key=?',(operation_key,)).fetchone()
            if old:return old[0]
            prior=db.execute('select kind,version from objects where id=?',(identifier,)).fetchone()
            if prior and prior[0]!=kind:raise ValueError('Object kind cannot change')
            version=prior[1] if prior else 0
            if expected_version is not None and version!=expected_version:raise ValueError('Record changed; reload before editing')
            event=uuid.uuid4().hex
            db.execute('insert or replace into objects values (?,?,?,?,?)',(identifier,kind,project,json.dumps(payload),version+1))
            db.execute('insert into events values (?,?,?,?,?,?,?,?,?,0)',(event,kind+'.saved',identifier,actor,datetime.now(timezone.utc).isoformat(),operation_key,1,project or 'personal',json.dumps({'version':version+1})))
            db.execute('insert into operations values (?,?)',(operation_key,event))
            return event
    def get(self,identifier):
        with self.transaction() as db:
            row=db.execute('select kind,project_id,payload,version from objects where id=?',(identifier,)).fetchone()
            return {'id':identifier,'kind':row[0],'project_id':row[1],'data':json.loads(row[2]),'version':row[3]} if row else None
