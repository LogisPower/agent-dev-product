"""Opt-in single confirmed-memory context, with canonical revalidation."""
import hashlib
from candidate_memory import RecallBody

def memory_row(app,project,record):
    rows,mapping=app.state.confirmed_memory_projection(project,[record])
    if len(rows)!=1:raise ValueError('One confirmed memory required')
    row=rows[0];meta=mapping[row['id']]
    return {'id':'memory:'+record,'project':project,'revision':meta['version'],'content':row['text'],'sha256':hashlib.sha256(row['text'].encode()).hexdigest(),'memory_provenance':{'record_id':record,'source_ids':meta['source_ids'],'evidence_revision':row['revision'],'source_sha256':row['source_sha256']}}

def combined_loader(app,loader,record):
    def load(project,ids):
        file_ids=[x for x in ids if not x.startswith('memory:')]
        rows=loader(project,file_ids)
        if record:rows.append(memory_row(app,project,record))
        return rows
    return load

def recall_checked(app,project,record,query,permissions,expected):
    result=app.state.confirmed_memory_recall(project,RecallBody(query=query,record_ids=[record]),permissions)
    if result.get('status')!='ready':raise ValueError('Selected memory unavailable; no silent memory fallback')
    hits=[h for h in result['matches'] if h['record_id']==record]
    if len(hits)!=1 or hits[0]['text']!=expected['content'] or hits[0]['version']!=expected['revision'] or hits[0]['source_ids']!=expected['memory_provenance']['source_ids']:raise ValueError('Selected memory recall did not verify')
    if memory_row(app,project,record)!=expected:raise ValueError('Memory changed during recall')
    return {'provider':'mnemosyne','method':result.get('method'),'record_id':record,'provenance':expected['memory_provenance'],'seconds':result.get('seconds'),'automatic_capture':False,'notice':'Explicit confirmed-memory projection only; no conversation enrollment'}
