"""Opt-in, source-checked derived recall. Canonical memory remains Logis-owned."""
import hashlib,json,os,pathlib,re,subprocess,sys,threading,time
ROOT=pathlib.Path(__file__).resolve().parent
LOCK=threading.Lock()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def sources(root,state,learned):
    allowed=set(state.get('context_policy',{}).get('sources',[])+[state['id']]);out=[]
    for m in learned:
        if m.get('status')!='confirmed' or m.get('source_id') not in allowed:continue
        if not re.fullmatch('[a-f0-9]{12}',m['source_id']) or not re.fullmatch('[a-f0-9]{24}',m['id']):continue
        p=pathlib.Path(root)/'Projects'/m['source_id']/'state.json'
        try:
            if p.is_symlink():continue
            with p.open('rb') as stream:raw=stream.read(2000001)
            if len(raw)>2000000:continue
            current=json.loads(raw)
            if current.get('archived') or current.get('context_policy',{}).get('learning',True) is False:continue
            i=m['message_index']
            if type(i) is not int or i<0:continue
            message=current['history'][i]
            if message['role']!='user' or not isinstance(m['text'],str) or not 1<=len(m['text'])<=2000:continue
            row={k:m[k] for k in ('id','text','source_id','message_index')}
            row['source_sha256']=digest(message)
            row['revision']=digest(row);out.append(row)
        except (OSError,ValueError,KeyError,IndexError,TypeError):continue
    if len(out)>64:raise ValueError('Too many confirmed memories; choose fewer sources')
    return sorted(out,key=lambda x:x['id'])
def recall(root,state,query,learned_provider):
    root=pathlib.Path(root)
    disabled={'status':'disabled','matches':[],'message':'Baseline memory is active; Mnemosyne is off.'}
    if state.get('context_policy',{}).get('mnemosyne') is not True or (root/'Data'/'mnemosyne.disabled').exists():return disabled
    if not LOCK.acquire(blocking=False):return {'status':'busy','matches':[],'message':'Optional memory busy; no Mnemosyne recall supplied.'}
    started=time.monotonic()
    try:
        rows=sources(root,state,learned_provider())
        payload={'project':state['id'],'query':query[:1000],'entries':rows}
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH'}}
        from inference_gate import inference_slot
        with inference_slot(root/'runtime'/'inference.lock',timeout=0):
            result=subprocess.run([sys.executable,'-B',str(root/'mnemosyne_worker.py'),str(root/'Data'/'mnemosyne'),str(root/'runtime'/'mnemosyne-libs')],input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or len(result.stdout)>100000:raise ValueError('Worker failed')
        value=json.loads(result.stdout)
        if value.get('status') not in ('ready','empty','unavailable') or not isinstance(value.get('matches'),list):raise ValueError('Invalid result')
        # Re-read canonical records after the worker; changes/withdrawals fail closed.
        if rows!=sources(root,state,learned_provider()):raise ValueError('Sources changed during recall')
        latest=json.loads((root/'Projects'/state['id']/'state.json').read_text(encoding='utf-8'))
        if latest.get('context_policy',{}).get('mnemosyne') is not True or (root/'Data'/'mnemosyne.disabled').exists():return disabled
        if latest.get('context_policy',{}).get('sources',[])!=state.get('context_policy',{}).get('sources',[]):raise ValueError('Source selection changed')
        valid={r['id']:r for r in rows}
        if len(value['matches'])>5 or sum(len(m['text']) for m in value['matches'])>6000:raise ValueError('Result bounds')
        for m in value['matches']:
            if {k:m[k] for k in valid.get(m['id'],{})}!=valid.get(m['id']) or m['id'] not in valid:raise ValueError('Unverified provenance')
        value['seconds']=round(time.monotonic()-started,3)
        value['message']=({'ready':str(len(value['matches']))+' confirmed source-backed memories recalled locally.','empty':'No confirmed memories in the selected sources.','unavailable':'Mnemosyne unavailable; no optional recall supplied.'})[value['status']]
        if value.get('method')=='local_nomic_dense_fallback':value['message']+=' Used verified Nomic similarity because Mnemosyne returned no lexical matches.'
        return value
    except Exception as error:return {'status':'unavailable','matches':[],'diagnostic':type(error).__name__,'message':'Optional memory unavailable or sources changed; no Mnemosyne recall supplied.'}
    finally:LOCK.release()

def status(root,state,learned_provider):
    root=pathlib.Path(root)
    if state.get('context_policy',{}).get('mnemosyne') is not True or (root/'Data'/'mnemosyne.disabled').exists():
        return {'status':'disabled','matches':[],'message':'Mnemosyne is off. Existing Logis memory behavior is unchanged.'}
    try:
        with (root/'Projects'/state['id']/'mnemosyne-recall.json').open('rb') as stream:raw=stream.read(100001)
        if len(raw)>100000:raise ValueError('Oversized receipt')
        value=json.loads(raw);current={r['id']:r for r in sources(root,state,learned_provider())}
        for m in value.get('matches',[]):
            if m['id'] not in current or any(m[k]!=v for k,v in current[m['id']].items()):
                return {'status':'stale','matches':[],'message':'Sources changed since the last recall. They will be rechecked before the next reply.'}
        value['message']='Last recall: '+value['message'];return value
    except FileNotFoundError:return {'status':'pending','matches':[],'message':'Enabled for this conversation. Confirm memories, then send a message to recall them.'}
    except Exception:return {'status':'unavailable','matches':[],'message':'Last recall cannot be verified.'}
