"""Explicit text revisions of immutable imported files; never writes legacy paths."""
import os,json,hashlib,uuid
from pathlib import Path,PurePosixPath
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from psycopg.types.json import Jsonb
SNAPSHOT=Path(os.environ['LOCALAPPDATA'])/'LogisRework/data/legacy-artifacts/20261024T135114Z'
TEXT={'.txt','.md','.html','.css','.js','.json','.csv','.py','.yaml','.yml'}
class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_sha256:str=Field(pattern='^[a-f0-9]{64}$')
    content:str=Field(max_length=131072)
def catalog(project):
    manifest=json.loads((SNAPSHOT/'manifest.json').read_text(encoding='utf-8'))
    result={}
    for name,meta in manifest['files'].items():
        parts=PurePosixPath(name).parts
        if len(parts)<4 or parts[0] not in ('Projects','Trash') or parts[1]!=project or parts[2]!='files':continue
        if '\\' in name or ':' in name or '..' in parts or name.startswith('/'):raise HTTPException(409,'Unsafe source manifest')
        key=hashlib.sha256(name.encode()).hexdigest()
        result[key]={'id':key,'name':'/'.join(parts[3:]),'source':name,**meta}
    return result
def original(item):
    path=SNAPSHOT/item['source']
    for part in [path,*path.parents]:
        if part.is_symlink() or part.is_junction():raise HTTPException(409,'Linked source unavailable')
        if part==SNAPSHOT:break
    if item['bytes']>131072 or path.stat().st_size>131072:raise HTTPException(422,'Text editor limit is 128 KiB')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise HTTPException(409,'Imported source checksum changed')
    try:text=raw.decode('utf-8')
    except UnicodeDecodeError:raise HTTPException(422,'Only UTF-8 text is editable')
    if Path(item['name']).suffix.lower() not in TEXT or '\x00' in text:raise HTTPException(422,'Unsupported text file')
    return text
def register_files(app,db,scope,allowed):
    def item_for(project,key):
        item=catalog(project).get(key)
        if not item:raise HTTPException(404,'File not found in project')
        return item
    def current(c,project,key,item):
        row=c.execute("SELECT id,payload FROM logis_candidate.runs WHERE project_id=%s AND agent_id='file-edit' AND payload->>'file_id'=%s ORDER BY (payload->>'revision')::int DESC LIMIT 1",(project,key)).fetchone()
        original(item) # also verifies preserved provenance has not changed
        return row['payload'] if row else {'content':original(item),'sha256':item['sha256'],'revision':0,'source':item['source'],'source_sha256':item['sha256']}
    @app.get('/api/projects/{project}/files')
    def listing(project:str,permissions=Depends(scope)):
        allowed(project,permissions)
        return list(catalog(project).values())
    @app.get('/api/projects/{project}/files/{key}')
    def read(project:str,key:str,permissions=Depends(scope)):
        allowed(project,permissions);item=item_for(project,key)
        with db() as c:return {**item,**current(c,project,key,item)}
    def chat_file_edit(project,key,body,permissions,origin):
        return perform_save(project,key,body,permissions,origin)
    app.state.chat_file_edit=chat_file_edit
    @app.post('/api/projects/{project}/files/{key}')
    def save(project:str,key:str,body:Edit,permissions=Depends(scope)):
        return perform_save(project,key,body,permissions,None)
    def perform_save(project,key,body,permissions,origin):
        allowed(project,permissions)
        if not permissions.get('write'):raise HTTPException(403,'Read-only credentials')
        item=item_for(project,key);raw=body.content.encode('utf-8')
        if len(raw)>131072 or '\x00' in body.content:raise HTTPException(422,'UTF-8 text limit exceeded')
        checksum=hashlib.sha256(raw).hexdigest()
        with db(False) as c:
            # The same row is locked by cancellation. Check and commit occur in
            # one transaction, so cancellation winning first prevents the edit.
            if origin:
                caller=c.execute("SELECT status,payload FROM logis_candidate.runs WHERE id=%s AND project_id=%s AND agent_id='local-chat' FOR UPDATE",(origin,project)).fetchone()
                if not caller or caller['status']!='running' or caller['payload'].get('cancel_requested'):raise HTTPException(409,'Origin stopped; file revision not committed')
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('file:'+project+':'+key,))
            state=c.execute('SELECT archived FROM logis_candidate.projects WHERE id=%s',(project,)).fetchone()
            if not state or state['archived']:raise HTTPException(409,'Archived project is read-only')
            prior=current(c,project,key,item)
            if prior['sha256']!=body.expected_sha256:raise HTTPException(409,'File changed; reload before saving. Draft not applied.')
            if checksum==prior['sha256']:return {**prior,'unchanged':True}
            payload={'file_id':key,'content':body.content,'sha256':checksum,'bytes':len(raw),'revision':prior['revision']+1,'parent_sha256':prior['sha256'],'source':item['source'],'source_sha256':item['sha256'],'checks':'not_run','executed':False}
            run=uuid.uuid4().hex
            c.execute("INSERT INTO logis_candidate.runs(id,project_id,agent_id,status,payload,occurrence_key) VALUES(%s,%s,'file-edit','completed',%s,%s)",(run,project,Jsonb(payload),'file-edit:'+run))
            if origin:
                c.execute("UPDATE logis_candidate.runs SET payload=payload || %s WHERE id=%s",(Jsonb({'settled_effect':{'kind':'file_revision','run_id':run,'sha256':checksum,'status':'committed'}}),origin))
            return payload
