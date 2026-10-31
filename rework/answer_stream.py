"""Bounded provisional answer snapshots. Never canonical memory or tool evidence."""
import contextvars,contextlib,threading,time,re

_sink=contextvars.ContextVar('logis_answer_sink',default=None)
def emit_content(text):
    sink=_sink.get()
    if sink is not None:
        try:sink(text)
        except Exception:pass  # Draft delivery failure must not re-run or fail final generation.
@contextlib.contextmanager
def capture(sink):
    token=_sink.set(sink)
    try:yield
    finally:_sink.reset(token)

SUSPICIOUS=re.compile(r'(?is)<\s*/?\s*(?:think|analysis|reasoning)\b|\b(?:Bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|-----BEGIN .*PRIVATE KEY)|\bI (?:have )?(?:ran|executed|deployed|searched|browsed|saved|verified)\b')
class Drafts:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.Lock();self.rows={}
    def start(self,project,run):
        with self.lock:
            now=self.clock()
            self.rows={k:v for k,v in self.rows.items() if now-v['started']<600}
            if len(self.rows)>=8:return None
            key=(project,run)
            if key in self.rows:return None
            self.rows[key]={'started':now,'raw':'','text':'','seq':0,'first_model_seconds':None,'blocked':False}
        def sink(part):
            if not isinstance(part,str):return
            with self.lock:
                row=self.rows.get(key)
                if not row or row['blocked']:return
                if part and row['first_model_seconds'] is None:row['first_model_seconds']=round(self.clock()-row['started'],4)
                row['raw']+=part
                if len(row['raw'])>64000 or SUSPICIOUS.search(row['raw']):
                    row.update(raw='',text='',blocked=True,seq=row['seq']+1);return
                # A completed segment avoids displaying a partial action/secret marker.
                ends=list(re.finditer(r'[.!?](?:\s|$)|\n',row['raw']))
                visible=row['raw'][:ends[-1].end()] if ends else ''
                if visible!=row['text']:row['text']=visible;row['seq']+=1
        return sink
    def snapshot(self,project,run,status,canceled=False):
        if status!='running' or canceled:return {'seq':0,'text':'','state':'final_only'}
        with self.lock:
            row=self.rows.get((project,run))
            if not row or self.clock()-row['started']>=600:return {'seq':0,'text':'','state':'final_only'}
            return {'seq':row['seq'],'text':row['text'],'state':'withheld' if row['blocked'] else 'provisional','first_model_seconds':row['first_model_seconds']}
    def finish(self,project,run):
        with self.lock:
            row=self.rows.pop((project,run),None)
            return {'first_model_answer_seconds':row['first_model_seconds'],'answer_stage_seconds':round(self.clock()-row['started'],4),'provisional_withheld':row['blocked']} if row else {'provisional_delivery':'unavailable; final-only fallback'}
