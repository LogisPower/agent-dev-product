"""Read-only binding to existing SQLite tasks; no second task store."""
import hashlib,json,re,sqlite3
from contextlib import closing
from pathlib import Path

def ident(value,size):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{%d}'%size,value):raise ValueError('Invalid binding identity')
    return value

def task_snapshot(database,task_id):
    ident(task_id,16);path=Path(database).absolute()
    if not path.is_file() or path.is_symlink():raise ValueError('Task database unavailable')
    # Never call workspace.db(): that helper creates schema as a side effect.
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('pragma query_only=ON')
        row=db.execute('select id,kind,title,detail,status,created,updated from items where id=?',(task_id,)).fetchone()
    if row is None or row[1]!='tasks':raise ValueError('Existing task required')
    if row[4] not in ('open','in_progress'):raise ValueError('Task must be explicitly accepted and active')
    encoded=json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    if len(encoded)>20000:raise ValueError('Task record exceeds binding budget')
    return {'id':row[0],'revision_sha256':hashlib.sha256(encoded).hexdigest()}

def validate(binding):
    if not isinstance(binding,dict) or set(binding)!={'version','task_id','project_id','run_id','task_revision_sha256'} or type(binding['version']) is not int or binding['version']!=1:raise ValueError('Invalid task binding')
    for key,size in [('task_id',16),('project_id',12),('run_id',32),('task_revision_sha256',64)]:ident(binding[key],size)
    return dict(binding)

def prepare(database,*,selected_task_id,selected_project_id,server_job,explicit_user_selection=False):
    """Call only from authenticated human run selection, never model/tool arguments."""
    if explicit_user_selection is not True:raise ValueError('Explicit human task/project selection required')
    project=ident(selected_project_id,12);run=ident(server_job.get('id'),32)
    if server_job.get('_project')!=project or server_job.get('task_binding') is not None:raise ValueError('Run scope mismatch or binding already present')
    task=task_snapshot(database,selected_task_id)
    return validate({'version':1,'task_id':task['id'],'project_id':project,'run_id':run,'task_revision_sha256':task['revision_sha256']})

def resolve(database,binding,server_job):
    b=validate(binding)
    if server_job.get('id')!=b['run_id'] or server_job.get('_project')!=b['project_id']:raise ValueError('Run binding mismatch')
    task=task_snapshot(database,b['task_id'])
    if task['revision_sha256']!=b['task_revision_sha256']:raise ValueError('Task changed; explicit reassociation required')
    return ({'id':b['task_id'],'project_id':b['project_id']},
            {'id':b['run_id'],'project_id':b['project_id'],'task_id':b['task_id']})
