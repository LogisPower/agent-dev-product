"""One disposable PostgreSQL test instance, never connects to live data."""
import json,os,socket,subprocess,sys,tempfile,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
live=Path(r'C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Builder')
sys.path[:0]=[str(root/'rework'),str(root),str(live/'rework/deps'),str(live/'runtime/agent-libs')]
native=live/'paperclip/node_modules/@embedded-postgres/windows-x64/native/bin'
temporary=Path(tempfile.mkdtemp(prefix='logis-foundation-check-'))
cluster=temporary/'rework/postgres-restore-synthetic';cluster.parent.mkdir()
def run(args):
    # pg_ctl descendants can inherit pipe handles on Windows. A file avoids
    # communicate() waiting indefinitely for an otherwise successful server start.
    with (temporary/'commands.log').open('a',encoding='utf-8') as log:
        result=subprocess.run([str(a) for a in args],stdout=log,stderr=log,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError((temporary/'commands.log').read_text()[-3000:])
    return result
started=False
try:
    run([native/'initdb.exe','-D',cluster,'-U','logis_test','-A','trust','--no-locale','-E','UTF8'])
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    run([native/'pg_ctl.exe','-D',cluster,'-l',temporary/'postgres.log','-o',f'-h 127.0.0.1 -p {port}','-w','-t','30','start']);started=True
    dsn=f'host=127.0.0.1 port={port} user=logis_test dbname=postgres connect_timeout=3'
    os.environ['LOGIS_DISPATCH_TEST_DSN']=dsn
    os.environ['LOGIS_DISPATCH_ARTIFACTS']=str(temporary/'artifacts')
    import psycopg
    with psycopg.connect(dsn,autocommit=True) as c:
        for name in ('001_canonical.sql','002_delivery.sql','003_event_feed.sql','004_understanding_jobs.sql','005_understanding_versions.sql'):
            c.execute((root/'rework'/name).read_text(),prepare=False)
    suite=unittest.TestSuite()
    for name in ('test_foundation','test_foundation_api','test_model_response','test_durable_dispatch','test_original_ui','test_project_lifecycle','test_project_export','test_activation_adapter','test_local_work_loop','test_local_work_api','test_local_work_plan','test_local_progress','test_local_planner','test_local_workflow','test_local_discovery','test_local_author','test_local_mixed_plan','test_project_verification','test_activation_entrypoint','test_local_provider_adapters'):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    for name in ('test_recursive_context','test_local_analysis'):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'tests':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'test_directory':str(temporary),'live_data_modified':False,'providers':'synthetic, plus real mock HTTP disconnect test'}
    (root/'foundation-test-results.json').write_text(json.dumps(report,indent=2))
    outcome=0 if result.wasSuccessful() else 1
finally:
    if started:run([native/'pg_ctl.exe','-D',cluster,'-m','fast','-w','stop'])
    print('Synthetic test state preserved at',temporary)
sys.exit(outcome)
