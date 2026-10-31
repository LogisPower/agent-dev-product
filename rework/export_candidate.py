"""Export already captured legacy snapshots; never read/write production during import."""
import json,sqlite3,uuid,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
snapshots=sorted((ROOT/'rehearsals').glob('*/legacy'))
if not snapshots:raise RuntimeError('Run migration rehearsal first')
snapshot=snapshots[-1];projects=[];messages=[];objects=[];evidence=[]
for path in snapshot.glob('*/*/state.json'):
    project=json.loads(path.read_text(encoding='utf-8'));projects.append(project)
    for index,message in enumerate(project.get('history',[])):
        identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,'logis:'+project['id']+':message:'+str(index)))
        messages.append({'id':identifier,'project_id':project['id'],'legacy_index':index,'role':message['role'],'content':message['content'],'checksum':hashlib.sha256(message['content'].encode()).hexdigest()})
db=sqlite3.connect(snapshot/'atlas.sqlite');db.row_factory=sqlite3.Row
try:
    objects=[dict(row) for row in db.execute('select * from items')]
    if db.execute("select 1 from sqlite_master where name='evidence'").fetchone():evidence=[dict(row) for row in db.execute('select * from evidence')]
finally:db.close()
(ROOT/'candidate-import.json').write_text(json.dumps({'projects':projects,'messages':messages,'objects':objects,'evidence':evidence}),encoding='utf-8')
print(json.dumps({'projects':len(projects),'messages':len(messages),'objects':len(objects),'evidence':len(evidence)}))
