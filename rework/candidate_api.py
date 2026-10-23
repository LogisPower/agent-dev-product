"""Isolated read-only candidate API; production routing is not changed."""
import sys,os,json,hmac
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'deps'))
from fastapi import FastAPI,Depends,Header,HTTPException
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager

def create_app(dsn,credentials):
    if not credentials:raise ValueError('Configure scoped credentials')
    app=FastAPI(title='Logis candidate API',docs_url=None,redoc_url=None,openapi_url=None)
    def scope(authorization:str=Header(default='')):
        if not authorization.startswith('Bearer '):raise HTTPException(401,'Authentication required')
        token=authorization.removeprefix('Bearer ')
        matched=next((value for key,value in credentials.items() if hmac.compare_digest(key,token)),None)
        if matched is None:raise HTTPException(401,'Authentication required')
        return matched
    @contextmanager
    def db():
        with psycopg.connect(dsn,row_factory=dict_row,options='-c default_transaction_read_only=on') as connection:
            directory=connection.execute('SHOW data_directory').fetchone()['data_directory']
            if '/rework/postgres-restore-' not in directory.replace('\\','/').lower():raise RuntimeError('Candidate API refuses non-isolated database')
            yield connection
    def allowed(project,permissions):
        if project not in permissions.get('projects',[]):raise HTTPException(404,'Project not found')
    @app.get('/health')
    def health():return {'service':'logis-candidate','mode':'read-only'}
    @app.get('/api/projects')
    def projects(permissions=Depends(scope)):
        with db() as connection:return connection.execute('SELECT id,name,archived FROM logis_candidate.projects WHERE id=ANY(%s) ORDER BY name',(permissions.get('projects',[]),)).fetchall()
    @app.get('/api/projects/{identifier}/messages')
    def messages(identifier:str,permissions=Depends(scope)):
        allowed(identifier,permissions)
        with db() as connection:return connection.execute('SELECT id,role,content,legacy_index FROM logis_candidate.messages WHERE project_id=%s ORDER BY legacy_index',(identifier,)).fetchall()
    @app.get('/api/projects/{identifier}/objects')
    def objects(identifier:str,permissions=Depends(scope)):
        allowed(identifier,permissions)
        with db() as connection:return connection.execute('SELECT id,kind,version,status,payload FROM logis_candidate.objects WHERE project_id=%s ORDER BY id',(identifier,)).fetchall()
    @app.get('/api/objects/{identifier}/evidence')
    def evidence(identifier:str,permissions=Depends(scope)):
        with db() as connection:
            obj=connection.execute('SELECT project_id FROM logis_candidate.objects WHERE id=%s',(identifier,)).fetchone()
            if not obj:raise HTTPException(404,'Object not found')
            allowed(obj['project_id'],permissions)
            return connection.execute('SELECT e.source_id,e.source_revision,e.quote,e.active FROM logis_candidate.evidence e JOIN logis_candidate.sources s ON s.id=e.source_id WHERE e.object_id=%s AND s.project_id=ANY(%s) AND s.deleted_at IS NULL',(identifier,permissions.get('projects',[]))).fetchall()
    return app
