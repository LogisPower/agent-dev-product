"""Read-only legacy capture and isolated migration/restore rehearsal."""
import json,sqlite3,hashlib,uuid,shutil
from pathlib import Path
from datetime import datetime,timezone
from records import Store
ROOT=Path(__file__).resolve().parent.parent

def connect_readonly(path):return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
def backup(source,destination):
    reader=connect_readonly(source);writer=sqlite3.connect(destination)
    try:reader.backup(writer)
    finally:reader.close();writer.close()

def main():
    run=ROOT/'rework/rehearsals'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');run.mkdir(parents=True)
    snapshot=run/'legacy';snapshot.mkdir();sources=[]
    for location in ('Projects','Trash'):
        for path in sorted((ROOT/location).glob('*/state.json')):
            raw=path.read_bytes();state=json.loads(raw)
            target=snapshot/location/path.parent.name;target.mkdir(parents=True);(target/'state.json').write_bytes(raw)
            sources.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(raw).hexdigest()})
    for path in (ROOT/'Data').glob('*.sqlite'):backup(path,snapshot/path.name)
    store=Store(run/'candidate.sqlite');expected={};evidence=[]
    def save(identifier,kind,data,project=None):
        if identifier in expected:raise ValueError('Legacy ID collision: '+identifier)
        expected[identifier]=(kind,data)
        store.put(identifier,kind,data,'import:'+identifier,actor='migration',project=project)
    for path in snapshot.glob('*/*/state.json'):
        state=json.loads(path.read_text(encoding='utf-8'));identifier=state['id']
        save(identifier,'project',{**state,'legacy_location':path.parent.parent.name},identifier)
        for index,message in enumerate(state.get('history',[])):
            mid=str(uuid.uuid5(uuid.NAMESPACE_URL,'logis:'+identifier+':message:'+str(index)))
            save(mid,'message',{**message,'legacy_index':index},identifier)
    legacy=snapshot/'atlas.sqlite'
    if legacy.exists():
        db=connect_readonly(legacy);db.row_factory=sqlite3.Row
        try:
            tables={x[0] for x in db.execute("select name from sqlite_master where type='table'")}
            if 'evidence' in tables:evidence=[dict(x) for x in db.execute('select * from evidence')]
            for row in db.execute('select * from items'):
                item=dict(row);links=[x for x in evidence if x['item_id']==item['id']]
                save(item['id'],item['kind'],{**item,'evidence':links},links[0]['project_id'] if links else None)
        finally:db.close()
    before=sqlite3.connect(run/'candidate.sqlite')
    try:count=before.execute('select count(*) from objects').fetchone()[0]
    finally:before.close()
    # Replaying identical import operations must not duplicate outbox events.
    for identifier,(kind,data) in expected.items():store.put(identifier,kind,data,'import:'+identifier,actor='migration')
    backup(run/'candidate.sqlite',run/'restored.sqlite');restored=Store(run/'restored.sqlite')
    for identifier,(kind,data) in expected.items():
        value=restored.get(identifier);assert value['kind']==kind and value['data']==data and value['version']==1
    db=connect_readonly(run/'restored.sqlite')
    try:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert db.execute('select count(*) from events').fetchone()[0]==count
    finally:db.close()
    changed=[s['path'] for s in sources if hashlib.sha256((ROOT/s['path']).read_bytes()).hexdigest()!=s['sha256']]
    report={'objects_verified':count,'source_state_files':len(sources),'evidence_links':len(evidence),'candidate_restore_verified':True,'replay_deduplication_verified':True,'source_changes_during_capture':changed,'full_system_restore_verified':False,'not_covered':['Paperclip PostgreSQL','Qdrant','original attachments/artifacts','secrets and Windows DPAPI recovery'],'production_modified':False}
    (run/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
