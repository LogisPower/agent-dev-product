"""Atomic mixed create/edit admission into the existing approved Foundation writer."""
import hashlib,json,re
from durable_tasks import encoded
from source_validation import validate_source
from local_work_plan import plan_identifier

class MixedPlans:
    def __init__(self,loop,author):self.loop,self.author=loop,author;loop.mixed_plans=self
    @staticmethod
    def _exists(c):return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mixed_file_plans'").fetchone() is not None
    def assert_unclaimed(self,project,source):
        foundation=self.author.foundation()
        if foundation is None:return
        with foundation.ledger.connection() as c:
            if self._exists(c) and c.execute('SELECT 1 FROM mixed_file_sources WHERE project=? AND source=?',(project,source)).fetchone():raise ValueError('Proposal already belongs to a mixed plan; inspect Background work')
    def list(self,project,principal):
        foundation=self.author.foundation()
        if foundation is None:raise ValueError('Approved Foundation writer is not connected')
        if foundation.files(project).root!=self.loop.files(project).root:raise PermissionError('Author and writer roots differ')
        with foundation.ledger.connection() as c:
            if not self._exists(c):return {'plans':[],'read_only':True}
            rows=c.execute('SELECT manifest FROM mixed_file_plans WHERE project=? ORDER BY rowid DESC LIMIT 21',(project,)).fetchall()
        result=[]
        for row in rows[:20]:
            item=json.loads(row['manifest'])
            result.append(self._public(item,foundation,project))
        return {'plans':result,'has_more':len(rows)>20,'read_only':True}
    def submit(self,project,key,title,selections,principal,allow_unsupported=False):
        if not isinstance(key,str) or not 1<=len(key)<=180 or not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError('Bounded key and title required')
        if not isinstance(selections,list) or not 1<=len(selections)<=8 or type(allow_unsupported) is not bool:raise ValueError('Select one to eight proposals')
        if not self.loop.authorize({'project':project,'payload':{'_principal':principal}}):raise PermissionError('Current mixed-plan scope required')
        foundation=self.author._writer(project,principal);files=self.loop.files(project)
        contract=hashlib.sha256(encoded([title,selections,principal,allow_unsupported]).encode()).hexdigest();identifier=plan_identifier(project,'mixed:'+key)
        with foundation.ledger.connection() as c:
            old=c.execute('SELECT contract,manifest FROM mixed_file_plans WHERE id=? AND project=?',(identifier,project)).fetchone() if self._exists(c) else None
        if old:
            if old['contract']!=contract:raise ValueError('Mixed-plan idempotency conflict')
            value=json.loads(old['manifest'])
            if value['root']!=str(files.root):raise PermissionError('Mixed plan root changed')
            return self._public(value,foundation,project)
        operations=[];sources=[];seen=set()
        for selection in selections:
            if type(selection) is not dict or set(selection)!={'task','version'} or not isinstance(selection['task'],str) or not re.fullmatch('[a-f0-9]{32}',selection['task']) or type(selection['version']) is not int:raise ValueError('Current proposal IDs and versions required')
            task=self.loop.ledger.get(project,selection['task']);payload=task['payload']
            if task['id'] in sources or task['status']!='completed' or task['version']!=selection['version'] or task['kind'] not in ('local_plan','local_author'):raise ValueError('Distinct completed current proposals required')
            if not self.loop.authorize(task):raise PermissionError('Original proposal scope withdrawn')
            if str(files.root)!=payload['_root']:raise PermissionError('Proposal root changed')
            sources.append(task['id']);self.assert_unclaimed(project,task['id'])
            with foundation.ledger.connection() as c:
                if c.execute('SELECT 1 FROM jobs WHERE project=? AND request_key=?',(project,'authored:'+task['id']+':write')).fetchone():raise ValueError('New-file proposal already submitted separately')
            with self.loop.ledger.connection() as c:
                if c.execute('SELECT 1 FROM jobs WHERE project=? AND request_key LIKE ?',(project,'plan:'+plan_identifier(project,'proposal:'+task['id'])+':%')).fetchone():raise ValueError('Edit proposal already submitted separately')
            for item in payload['files']:files.verify(item['path'],item['sha256'])
            if task['kind']=='local_author':
                proposal=task['result']['proposal'];self.author._missing(files,proposal['path']);items=[dict(proposal)]
            else:
                snapshots={v['path']:v for v in payload['files']};items=[]
                for step in task['result']['proposal']['steps']:
                    edit=step['edit'];source=snapshots[edit['path']]
                    if source['content'].count(edit['old'])!=1:raise ValueError('Ambiguous stored edit')
                    items.append({'path':edit['path'],'content':source['content'].replace(edit['old'],edit['new'],1),'expected_sha256':edit['expected_sha256']})
            for item in items:
                if len(operations)>=8 or sum(len(v['payload']['content'].encode()) for v in operations)+len(item['content'].encode())>65536:raise ValueError('Mixed plan exceeds eight files or 64 KB')
                path=files.relative(item['path'])
                if path.casefold() in seen:raise ValueError('One operation per file in a mixed plan')
                seen.add(path.casefold());validation=validate_source(path,item['content'])
                if validation['status'] in ('failed','unavailable'):raise ValueError('Syntax validation '+validation['status']+' for '+path)
                if validation['status']=='unsupported' and not allow_unsupported:raise ValueError('Unsupported language requires explicit manual-review acknowledgement: '+path)
                operations.append({'payload':{**item,'_principal':principal},'validation':validation,'source':task['id']})
        if len(operations)>8 or sum(len(v['payload']['content'].encode()) for v in operations)>65536:raise ValueError('Mixed plan exceeds eight files or 64 KB')
        with foundation.ledger.transaction() as c:
            c.execute('CREATE TABLE IF NOT EXISTS mixed_file_plans(id TEXT PRIMARY KEY,project TEXT NOT NULL,contract TEXT NOT NULL,manifest TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS mixed_file_sources(project TEXT NOT NULL,source TEXT NOT NULL,plan TEXT NOT NULL,PRIMARY KEY(project,source))')
            old=c.execute('SELECT contract,manifest FROM mixed_file_plans WHERE id=?',(identifier,)).fetchone()
            if old:
                if old['contract']!=contract:raise ValueError('Mixed-plan idempotency conflict')
                value=json.loads(old['manifest'])
            else:
                tasks=[];previous=None;steps=[]
                for source in sources:
                    if c.execute('SELECT 1 FROM mixed_file_sources WHERE project=? AND source=?',(project,source)).fetchone():raise ValueError('Proposal was concurrently assigned to another mixed plan')
                    c.execute('INSERT INTO mixed_file_sources VALUES(?,?,?)',(project,source,identifier))
                for index,operation in enumerate(operations):
                    payload=operation['payload'];dependencies=[] if previous is None else [{'task':previous['id'],'path':previous['payload']['path']}]
                    pair=foundation.ledger.submit_verified_write(project,'mixed:'+identifier+':'+str(index),payload,dependencies,_connection=c)
                    tasks.extend([pair['write']['id'],pair['verify']['id']]);previous=pair['write']
                    steps.append({'path':payload['path'],'operation':'edit' if payload.get('expected_sha256') else 'create','source':operation['source'],'validation':operation['validation']})
                value={'id':identifier,'title':title,'root':str(files.root),'tasks':tasks,'steps':steps,'sources':sources,'approval_required':True,'started':False}
                c.execute('INSERT INTO mixed_file_plans VALUES(?,?,?,?)',(identifier,project,contract,encoded(value)))
        return self._public(value,foundation,project)
    @staticmethod
    def _public(value,foundation,project):
        result={k:v for k,v in value.items() if k!='root'}
        result['tasks']=[foundation.query(project,'task',task=task) for task in value['tasks']]
        return result
