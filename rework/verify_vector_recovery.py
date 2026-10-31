import sys,json,sqlite3,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
TARGET=ROOT/'rework/vector-restore-check';TARGET.mkdir(exist_ok=True)
source=ROOT/'Data/vector-db';before=(source/'meta.json').read_bytes();count=0
for path in source.rglob('storage.sqlite'):
    target=TARGET/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True)
    reader=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);writer=sqlite3.connect(target)
    try:
        started=time.monotonic()
        def progress(*args):
            if time.monotonic()-started>20:raise TimeoutError('Vector snapshot timed out')
        reader.backup(writer,pages=128,progress=progress);assert writer.execute('pragma integrity_check').fetchone()[0]=='ok';count+=1
    finally:reader.close();writer.close()
assert before==(source/'meta.json').read_bytes(),'Collection metadata changed during snapshot; retry'
(TARGET/'meta.json').write_bytes(before)
sys.path.insert(0,str(ROOT/'runtime/agent-libs'))
from qdrant_client import QdrantClient
client=QdrantClient(path=str(TARGET));collections=client.get_collections().collections
results=[]
try:
    for collection in collections:
        result=client.scroll(collection.name,limit=1,with_vectors=True,with_payload=True)
        results.append({'collection':collection.name,'count':client.count(collection.name).count,'sample_read':bool(result[0])})
finally:client.close()
report={'sqlite_files_integrity_verified':count,'restored_qdrant_opened':True,'collections':results,'coordinated_system_snapshot':False}
(ROOT/'rework/vector-recovery-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
