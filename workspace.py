"""Persistent workspace records and real service snapshots for the Atlas navigation."""
import json,sqlite3,time,uuid,urllib.request,hashlib,re
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PAPERCLIP_CACHE=None
PAPERCLIP_CHECKED=0
KINDS={'tasks','cases','routines','pipelines','artifacts','skills','decisions','conference','agents','org'}
def db():
    (ROOT/'Data').mkdir(exist_ok=True);c=sqlite3.connect(ROOT/'Data/atlas.sqlite')
    c.execute('CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, kind TEXT, title TEXT, detail TEXT, status TEXT, created REAL, updated REAL)')
    return c
def items(kind):
    if kind not in KINDS:raise ValueError('Unknown record type')
    with closing(db()) as c:
        return [{**dict(zip(('id','kind','title','detail','status','created','updated'),row)),**source_links().get(row[0],{})} for row in c.execute('SELECT * FROM items WHERE kind=? ORDER BY updated DESC',(kind,)).fetchall()]
def save(data):
    kind=data.get('kind');title=str(data.get('title','')).strip()[:180];detail=str(data.get('detail',''))[:12000]
    if kind not in KINDS or not title:raise ValueError('Provide a valid type and title')
    status=data.get('status','draft' if kind in ('routines','pipelines','agents') else 'open')
    if status not in ('open','in_progress','done','draft','archived'):raise ValueError('Invalid status')
    identifier=data.get('id') or uuid.uuid4().hex[:16]
    with closing(db()) as c, c:
        prior=c.execute('SELECT kind,created FROM items WHERE id=?',(identifier,)).fetchone()
        if prior and prior[0]!=kind:raise ValueError('Record type cannot change')
        c.execute('INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?)',(identifier,kind,title,detail,status,prior[1] if prior else time.time(),time.time()))
    return {'id':identifier,'saved':True}
def paperclip(path='/health'):
    global PAPERCLIP_CACHE,PAPERCLIP_CHECKED
    if path=='/health' and PAPERCLIP_CACHE is not None and time.time()-PAPERCLIP_CHECKED<10:return PAPERCLIP_CACHE
    try:
        with urllib.request.urlopen('http://127.0.0.1:3100/api'+path,timeout=1) as r:result={'online':True,'data':json.load(r)}
    except Exception as e:result={'online':False,'reason':'Installed. Windows blocked its database startup. Run Start Paperclip.ps1 from Windows to retry. Agent scheduling is not available yet.','diagnostic':'uv_os_get_passwd returned ENOMEM in the managed Windows session'}
    if path=='/health':PAPERCLIP_CACHE=result;PAPERCLIP_CHECKED=time.time()
    return result
def summary(projects,jobs):
    active=[{'id':i,'phase':j.get('phase'),'started':j.get('started')} for i,j in jobs.items() if j.get('status')=='running']
    return {'projects':len(projects),'open_tasks':sum(x['status'] not in ('done','archived') for x in items('tasks')),'active_jobs':active,'tasks':items('tasks')[:6],'recent_projects':projects[:6],'paperclip':paperclip(),'models':[{'name':'Bonsai 2 27B','url':'http://127.0.0.1:8081'},{'name':'Bonsai 2 9B Vision','url':'http://127.0.0.1:8082'}],'stack':{'workflow':'LangGraph / SQLite checkpoints','retrieval':'Qdrant local + Nomic embeddings','tools':'Shared MCP registry'}}
def activity(projects):
    result=[]
    for p in projects:
        f=ROOT/'Projects'/p['id']/'actions.jsonl'
        if f.exists():
            for line in f.read_text(encoding='utf-8').splitlines()[-20:]:
                try:result.append({**json.loads(line),'project':p['name'],'project_id':p['id']})
                except Exception:pass
    return sorted(result,key=lambda x:x.get('time',''),reverse=True)[:100]


def sync_conversations():
    """Deterministic explicit task/decision extraction; suggestions never execute."""
    import conversation_memory
    with closing(db()) as c,c:
        c.execute('create table if not exists evidence (item_id text primary key, project_id text, message_index integer, source_text text, active integer)')
        c.execute('update evidence set active=0')
        for conversation in conversation_memory.overview()['conversations']:
            if not conversation['context'].get('learning',True):continue
            for message in conversation['messages']:
                for line in message['text'].splitlines():
                    match=re.match(r'(?i)^\s*(task|todo|decision|we decided|I decided)\s*:\s*(.+)',line)
                    if not match:
                        natural=re.match(r'(?i)^\s*(?:please |can you |could you |we need to |I need to |I need you to |remind me to |add a task to |make sure to )(build|create|fix|update|review|test|finish|send|prepare|schedule|check|write|implement|organize)\b(.+)',line)
                        if not natural or re.search(r"(?i)\b(don.t|do not|hypothetical|example|maybe|if we)\b",line):continue
                        line='Task: '+natural[1]+natural[2]
                        match=re.match(r'(?i)^(task):\s*(.+)',line)
                    kind='tasks' if match[1].lower() in ('task','todo') else 'decisions'
                    title=match[2].strip()[:180]
                    identifier=hashlib.sha256((conversation['id']+str(message['index'])+line).encode()).hexdigest()[:16]
                    detail='Source: '+conversation['name']+' Ã‚Â· message '+str(message['index']+1)+'\n'+line
                    c.execute('insert or ignore into items values (?,?,?,?,?,?,?)',(identifier,kind,title,detail,'draft',time.time(),time.time()))
                    c.execute('insert or replace into evidence values (?,?,?,?,1)',(identifier,conversation['id'],message['index'],line))

        for conversation in conversation_memory.overview()['conversations']:
            if not conversation['context'].get('learning',True):continue
            cache=ROOT/'Projects'/conversation['id']/'understanding.json'
            if not cache.exists():continue
            messages={m['index']:m['text'] for m in conversation['messages']}
            for item in json.loads(cache.read_text(encoding='utf-8')).get('items',[]):
                if item['kind'] not in ('task','decision') or item['quote'] not in messages.get(item['message_index'],''):continue
                kind='tasks' if item['kind']=='task' else 'decisions'
                existing=c.execute('select e.item_id,e.source_text from evidence e join items i on i.id=e.item_id where e.project_id=? and e.message_index=? and i.kind=?',(conversation['id'],item['message_index'],kind)).fetchall()
                matching=[x for x in existing if item['quote'] in x[1] or x[1] in item['quote']]
                if matching:
                    for prior in matching:c.execute('update evidence set active=1 where item_id=?',(prior[0],))
                    continue
                identifier=hashlib.sha256((conversation['id']+str(item['message_index'])+item['quote']).encode()).hexdigest()[:16]
                c.execute('insert or ignore into items values (?,?,?,?,?,?,?)',(identifier,kind,item['text'][:180],'Source: '+conversation['name']+'\n'+item['quote'],'draft',time.time(),time.time()))
                c.execute('insert or replace into evidence values (?,?,?,?,1)',(identifier,conversation['id'],item['message_index'],item['quote']))

def source_links():
    with closing(db()) as c:
        try:return {x[0]:{'project_id':x[1],'message_index':x[2],'source_active':bool(x[3])} for x in c.execute('select item_id,project_id,message_index,active from evidence')}
        except sqlite3.OperationalError:return {}

def agent_snapshot(jobs):
    runs=[]
    for folder in (ROOT/'Projects').iterdir():
        path=folder/'state.json'
        if not path.exists():continue
        state=json.loads(path.read_text(encoding='utf-8'))
        if state.get('archived'):continue
        if folder.name in jobs:runs.append({'project':state['name'],'project_id':folder.name,**jobs[folder.name]})
        elif (folder/'last-run.json').exists():runs.append({'project':state['name'],'project_id':folder.name,**json.loads((folder/'last-run.json').read_text(encoding='utf-8'))})
    return {'records':items('agents'),'jobs':runs,'paperclip':paperclip(),'paperclip_companies':paperclip('/companies')}
