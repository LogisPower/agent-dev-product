"""Verified file recovery bundle; does not claim a consistent live DB snapshot."""
import json,hashlib,zipfile,gzip,shutil,sqlite3,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent.parent

def digest(data):return hashlib.sha256(data).hexdigest()
def main():
    target=ROOT/'rework/recovery'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');target.mkdir(parents=True)
    manifest=[];errors=[];changed=[]
    roots=[ROOT/x for x in ('Projects','Trash','PC Files')]
    with zipfile.ZipFile(target/'project-assets.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for base in roots:
            if not base.exists():continue
            for path in base.rglob('*'):
                if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
                    errors.append({'path':str(path.relative_to(ROOT)),'error':'linked path excluded'});continue
                if not path.is_file():continue
                if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in path.parents if p!=ROOT and p.is_relative_to(ROOT)):
                    errors.append({'path':str(path.relative_to(ROOT)),'error':'linked ancestor excluded'});continue
                if path.suffix in ('.sqlite','.sqlite3','.db') or path.name.endswith(('-wal','-shm','.tmp')):continue
                try:
                    before=path.stat();data=path.read_bytes();after=path.stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):changed.append(str(path.relative_to(ROOT)));continue
                    relative=path.relative_to(ROOT).as_posix();archive.writestr(relative,data);manifest.append({'path':relative,'bytes':len(data),'sha256':digest(data)})
                except OSError as e:errors.append({'path':str(path.relative_to(ROOT)),'error':str(e)})
    restored=target/'restore-check';restored.mkdir()
    with zipfile.ZipFile(target/'project-assets.zip') as archive:
        assert archive.testzip() is None
        for entry in manifest:
            # Restore only manifest paths produced by this program, within a new directory.
            destination=(restored/entry['path']).resolve()
            if not destination.is_relative_to(restored.resolve()):raise ValueError('Unsafe archive path')
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(archive.read(entry['path']))
            assert digest(destination.read_bytes())==entry['sha256']
    databases=[]
    for base in [ROOT/'Data',ROOT/'Projects',ROOT/'Trash']:
        for source in base.rglob('*.sqlite'):
            if 'paperclip' in source.relative_to(ROOT).parts or 'vector-db' in source.relative_to(ROOT).parts:continue
            destination=target/'sqlite'/source.relative_to(ROOT);destination.parent.mkdir(parents=True,exist_ok=True)
            reader=writer=None
            try:
                reader=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
                writer=sqlite3.connect(destination);started=time.monotonic()
                def progress(status,remaining,total):
                    if time.monotonic()-started>15:raise TimeoutError('SQLite backup exceeded 15 seconds')
                reader.backup(writer,pages=128,progress=progress)
                assert writer.execute('pragma integrity_check').fetchone()[0]=='ok'
                databases.append(str(source.relative_to(ROOT)))
            except Exception as e:errors.append({'path':str(source.relative_to(ROOT)),'error':str(e)})
            finally:
                if reader:reader.close()
                if writer:writer.close()
    dumps=sorted((ROOT/'Data/paperclip').rglob('*.sql.gz'),key=lambda p:p.stat().st_mtime,reverse=True)
    paperclip={'available':bool(dumps),'restored_into_postgresql':False}
    if dumps:
        source=dumps[0];destination=target/source.name;shutil.copy2(source,destination)
        # Streaming through gzip validates decompression and trailer CRC without loading the whole dump.
        size=0
        with gzip.open(destination,'rb') as stream:
            while True:
                chunk=stream.read(1024*1024)
                if not chunk:break
                size+=len(chunk)
        paperclip.update(file=source.name,source_mtime=source.stat().st_mtime,decompressed_bytes=size,gzip_integrity_verified=True)
    report={'sqlite_databases_verified':databases,'assets':len(manifest),'restored_file_hashes_verified':True,'errors':errors,'changed_during_capture':changed,'paperclip':paperclip,'coordinated_snapshot':False,'excluded':'Live databases, Qdrant, secret recovery and Windows-bound account encryption need separate handling.'}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2));(target/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
