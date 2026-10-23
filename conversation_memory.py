"""Source-linked conversation inventory. No inferred facts are treated as confirmed."""
import json,re,hashlib,sqlite3
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def overview():
    conversations=[]
    for p in (ROOT/'Projects').glob('*/state.json'):
        try:
            s=json.loads(p.read_text(encoding='utf-8'))
            if s.get('archived'):continue
            messages=[{'index':i,'text':m['content'],'time':m.get('time')} for i,m in enumerate(s.get('history',[])) if m.get('role')=='user']
            conversations.append({'id':s['id'],'name':s['name'],'messages':messages,'checkpoint':s.get('checkpoint',{}),'context':s.get('context_policy',{'sources':[],'learning':True})})
        except (ValueError,OSError,KeyError):continue
    return {'conversations':conversations,'total_messages':sum(len(x['messages']) for x in conversations)}

def context(state):
    allowed=set(state.get('context_policy',{}).get('sources',[]))
    return [{'source_id':x['id'],'source':x['name'],'user_messages':x['messages'][-4:]} for x in overview()['conversations'] if x['id'] in allowed and x['id']!=state['id']][:8]


def learned():
    result=[]
    for c in overview()['conversations']:
        if c['context'].get('learning',True) is False:continue
        for m in c['messages']:
            for sentence in re.split(r'[\n.!?]+',m['text']):
                sentence=sentence.strip()
                if not re.match(r'(?i)^(I prefer |I like |My goal is |Remember that |I want you to always )',sentence):continue
                if re.search(r'(?i)password|secret|token|diagnos|medical|bank|social security',sentence):continue
                key=hashlib.sha256((c['id']+str(m['index'])+sentence).encode()).hexdigest()[:24]
                result.append({'id':key,'text':sentence,'source_id':c['id'],'source':c['name'],'message_index':m['index'],'status':'suggested'})
    for c in overview()['conversations']:
        if not c['context'].get('learning',True):continue
        cache=ROOT/'Projects'/c['id']/'understanding.json'
        if not cache.exists():continue
        messages={m['index']:m['text'] for m in c['messages']}
        for item in json.loads(cache.read_text(encoding='utf-8')).get('items',[]):
            if item['kind'] not in ('preference','goal') or item['quote'] not in messages.get(item['message_index'],''):continue
            key=hashlib.sha256((c['id']+str(item['message_index'])+item['quote']).encode()).hexdigest()[:24]
            if any(x['id']==key for x in result):continue
            result.append({'id':key,'text':item['text'],'source_id':c['id'],'source':c['name'],'message_index':item['message_index'],'status':'suggested'})
    with closing(memory_db()) as db:
        overrides={r[0]:r[1:] for r in db.execute('select id,text,status from overrides')}
    for item in result:
        if item['id'] in overrides:item['text'],item['status']=overrides[item['id']]
    return [x for x in result if x['status']!='deleted']

def memory_db():
    (ROOT/'Data').mkdir(exist_ok=True)
    db=sqlite3.connect(ROOT/'Data/conversation-memory.sqlite')
    db.execute('create table if not exists overrides (id text primary key,text text,status text)')
    return db

def update_memory(data):
    entry=next((x for x in learned() if x['id']==data.get('id')),None)
    if not entry:raise ValueError('Memory source no longer exists')
    status=data.get('status','confirmed')
    if status not in ('confirmed','suggested','deleted'):raise ValueError('Invalid memory status')
    text=str(data.get('text',entry['text'])).strip()
    if not 1<=len(text)<=2000:raise ValueError('Memory must contain 1â€“2000 characters')
    with closing(memory_db()) as db,db:
        db.execute('insert or replace into overrides values (?,?,?)',(entry['id'],text,status))
    return {'saved':True}
