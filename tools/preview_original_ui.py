"""Disposable browser fixture. No live data or model calls. Stop via stop file."""
import json,os,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
live=Path(r'C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Builder')
sys.path[:0]=[str(root/'rework'),str(root),str(live/'rework/deps'),str(live/'runtime/agent-libs')]
native=live/'paperclip/node_modules/@embedded-postgres/windows-x64/native/bin'
temporary=Path(tempfile.mkdtemp(prefix='logis-browser-check-'))
cluster=temporary/'rework/postgres-restore-synthetic';cluster.parent.mkdir()
def command(args):
    with (temporary/'commands.log').open('a') as log:
        subprocess.run([str(x) for x in args],stdout=log,stderr=log,check=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
started=False
try:
    command([native/'initdb.exe','-D',cluster,'-U','logis_test','-A','trust','--no-locale','-E','UTF8'])
    pgport=free_port();command([native/'pg_ctl.exe','-D',cluster,'-l',temporary/'postgres.log','-o',f'-h 127.0.0.1 -p {pgport}','-w','start']);started=True
    import psycopg,uvicorn
    from psycopg.types.json import Jsonb
    dsn=f'host=127.0.0.1 port={pgport} user=logis_test dbname=postgres'
    with psycopg.connect(dsn,autocommit=True) as c:
        for name in ('001_canonical.sql','002_delivery.sql','003_event_feed.sql','004_understanding_jobs.sql','005_understanding_versions.sql'):c.execute((root/'rework'/name).read_text(),prepare=False)
        c.execute("INSERT INTO logis_candidate.projects(id,name) VALUES('browser-synthetic','Synthetic Logis project')")
        c.execute("INSERT INTO logis_candidate.objects(id,kind,project_id,status,payload) VALUES('browser-task','tasks','browser-synthetic','open',%s)",(Jsonb({'title':'Verify original interface','detail':'Synthetic evidence only.'}),))
        import hashlib
        message='Synthetic source: preserve the original Logis design.'
        c.execute("INSERT INTO logis_candidate.sources(id,project_id,kind,checksum,payload) VALUES('browser-source','browser-synthetic','conversation',%s,%s)",(hashlib.sha256(message.encode()).hexdigest(),Jsonb({'content':message})))
        c.execute("INSERT INTO logis_candidate.messages VALUES('browser-message','browser-synthetic','browser-source',0,'user',%s)",(message,))
    from candidate_api import create_app
    import candidate_build
    candidate_build.DATA=temporary/'artifacts'
    def chat(messages,**kwargs):return json.dumps({'goal':'answer','answer':'Synthetic provider reply: the original Logis interface is connected.','actions':[]})
    def build(messages):
        from provider_cancel import current, ProviderCanceled
        # A bounded artificial delay lets browser checks exercise status/cancel.
        for _ in range(40):
            time.sleep(.25)
            if current.get()():raise ProviderCanceled()
        return json.dumps({'html':'<!doctype html><html><body>Synthetic Logis build</body></html>'})
    from foundation_runtime import Foundation
    files=temporary/'project';files.mkdir();(files/'readme.txt').write_text('Synthetic project file.\n')
    foundation=Foundation(temporary/'foundation',lambda project:files if project=='browser-synthetic' else None)
    app=create_app(dsn,{'synthetic-browser-token':{'projects':['browser-synthetic'],'write':True}},background_chat=True,original_ui=True,request_chat=chat,request_build=build,context_counter=lambda payload:len(json.dumps(payload))//3,foundation=foundation)
    app.state.local_langchain_enabled=False
    port=free_port();server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning'))
    from outbox_worker import Worker
    def project_events():
        worker=Worker(dsn)
        while not server.should_exit:
            worker.once();time.sleep(.25)
    threading.Thread(target=project_events,daemon=True).start()
    info={'url':f'http://127.0.0.1:{port}/logis','stop_file':str(temporary/'stop'),'directory':str(temporary),'pid':os.getpid(),'dsn':dsn}
    (root/'browser-preview-local.json').write_text(json.dumps(info,indent=2))
    def stop_watch():
        deadline=time.monotonic()+1200
        while time.monotonic()<deadline and not (temporary/'stop').exists():time.sleep(.5)
        server.should_exit=True
    threading.Thread(target=stop_watch,daemon=True).start()
    server.run()
finally:
    if started:command([native/'pg_ctl.exe','-D',cluster,'-m','fast','-w','stop'])
