"""Single-operation optional memory worker. Only derived project-local data is written."""
import os,sys,json,pathlib,hashlib,time

MODEL='text-embedding-nomic-embed-text-v1.5'
URL='http://127.0.0.1:1234/v1/embeddings'
def execute(request,base,vendor):
    import re
    project=request['project']
    if not re.fullmatch('[a-f0-9]{12}',project):raise ValueError('Invalid project')
    entries=request['entries'];query=request['query']
    if not isinstance(entries,list) or len(entries)>64 or not isinstance(query,str) or len(query)>1000:raise ValueError('Memory request exceeds bounds')
    expected={}
    for row in entries:
        if set(row)!={'id','text','source_id','message_index','source_sha256','revision'} or not re.fullmatch('[a-f0-9]{24}',row['id']) or not re.fullmatch('[a-f0-9]{12}',row['source_id']):raise ValueError('Invalid source')
        if not isinstance(row['text'],str) or not 1<=len(row['text'])<=2000 or type(row['message_index']) is not int:raise ValueError('Invalid content')
        if row['id'] in expected:raise ValueError('Duplicate source')
        expected[row['id']]=row
    data=pathlib.Path(base)/project
    data.mkdir(parents=True,exist_ok=True)
    if data.is_symlink():raise ValueError('Unsafe data path')
    keep={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH'}}
    os.environ.clear();os.environ.update(keep)
    os.environ.update(USERPROFILE=str(data/'home'),HERMES_HOME=str(data/'home'),MNEMOSYNE_DATA_DIR=str(data),
        MNEMOSYNE_EMBEDDING_API_URL='http://127.0.0.1:1234/v1',MNEMOSYNE_EMBEDDING_MODEL=MODEL,MNEMOSYNE_EMBEDDING_DIM='768',
        MNEMOSYNE_EMBEDDING_QUERY_PREFIX='search_query: ',MNEMOSYNE_EMBEDDING_DOC_PREFIX='search_document: ',
        MNEMOSYNE_CROSS_SESSION='0',MNEMOSYNE_ENHANCED_RECALL='0',MNEMOSYNE_POLYPHONIC_RECALL='0',MNEMOSYNE_PROACTIVE_LINKING='0')
    os.environ.update(MNEMOSYNE_LLM_ENABLED='false',MNEMOSYNE_HOST_LLM_ENABLED='false',
        MNEMOSYNE_AUTO_SLEEP_ENABLED='false',MNEMOSYNE_SLEEP_MODEL_REFRESH_ENABLED='false',
        MNEMOSYNE_PERSONA_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    def audit(event,args):
        if event=='socket.connect' and args[1][:2]!=('127.0.0.1',1234):raise RuntimeError('Only local Nomic is allowed')
    sys.addaudithook(audit)
    sys.path.insert(0,str(vendor))
    import sqlite3
    original_connect=sqlite3.connect
    def derived_connect(database,*args,**kwargs):
        target=pathlib.Path(database).resolve()
        if not target.is_relative_to(data.resolve()):raise RuntimeError('Only derived project databases allowed')
        conn=original_connect(database,*args,**kwargs)
        conn.execute('PRAGMA journal_mode=WAL')
        # Only this reconstructible sidecar uses NORMAL. No canonical database
        # is opened here. A power failure may lose recent derived captures;
        # every subsequent use reconciles them from confirmed canonical sources.
        conn.execute('PRAGMA synchronous=NORMAL')
        return conn
    sqlite3.connect=derived_connect
    from mnemosyne.core import local_llm
    def no_download(*args,**kwargs):raise RuntimeError('Additional models forbidden')
    local_llm._download_model=no_download
    local_llm.LLM_ENABLED=False;local_llm.HOST_LLM_ENABLED=False
    from mnemosyne import Mnemosyne
    from mnemosyne.core import embeddings as emb
    import numpy as np,urllib.request
    failures=[];calls=[]
    # Replace only SDK transport in this isolated child: one bounded request, no
    # inherited credentials/proxy, redirects, remote fallback or implicit retries.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise RuntimeError('Redirect forbidden')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def vectors(texts):
        try:
            if not 1<=len(texts)<=64 or any(len(t)>2100 for t in texts):raise ValueError('Embedding bounds')
            started=time.monotonic()
            req=urllib.request.Request(URL,data=json.dumps({'model':MODEL,'input':texts}).encode(),headers={'Content-Type':'application/json'})
            with opener.open(req,timeout=4) as response:raw=response.read(2000000)
            body=json.loads(raw);rows=sorted(body['data'],key=lambda x:x['index'])
            if body.get('model')!=MODEL or [x['index'] for x in rows]!=list(range(len(texts))):raise ValueError('Embedding identity mismatch')
            result=np.array([x['embedding'] for x in rows],dtype=np.float32)
            if result.shape!=(len(texts),768) or not np.isfinite(result).all() or not np.allclose(np.linalg.norm(result,axis=1),1,atol=.02):raise ValueError('Invalid Nomic vectors')
            calls.append({'batch':len(texts),'seconds':round(time.monotonic()-started,4)})
            return result
        except Exception:
            failures.append(True);raise RuntimeError('Local Nomic embedding unavailable') from None
    emb._embed_api=vectors
    memory=Mnemosyne(session_id=project,db_path=data/'memory.sqlite')
    db=memory.conn
    db.execute('CREATE TABLE IF NOT EXISTS logis_sources(source_id TEXT PRIMARY KEY,memory_id TEXT,revision TEXT)');db.commit()
    stored={r[0]:(r[1],r[2]) for r in db.execute('SELECT source_id,memory_id,revision FROM logis_sources')}
    # Remove withdrawn/changed captures before any embedding call, including outages.
    for sid,(mid,revision) in list(stored.items()):
        if sid not in expected or expected[sid]['revision']!=revision:
            memory.forget(mid);db.execute('DELETE FROM logis_sources WHERE source_id=?',(sid,));db.commit();stored.pop(sid)
    mapped={value[0] for value in stored.values()}
    for (mid,) in list(db.execute('SELECT id FROM working_memory')):
        if mid not in mapped:memory.forget(mid) # interrupted earlier capture, derived only
    for sid,(mid,revision) in list(stored.items()):
        if memory.get(mid) is None:
            db.execute('DELETE FROM logis_sources WHERE source_id=?',(sid,));db.commit();stored.pop(sid)
    if not entries:return {'status':'empty','matches':[],'captured':0,'calls':calls}
    # Forces a fresh actual vector even if the SDK would otherwise return keywords.
    emb._embed_query_cached.cache_clear()
    probe=emb.embed_query('Logis local memory backend compatibility probe v1')
    signature=hashlib.sha256(np.round(probe,5).tobytes()).hexdigest()
    db.execute('CREATE TABLE IF NOT EXISTS logis_backend(signature TEXT)')
    prior=db.execute('SELECT signature FROM logis_backend').fetchone()
    if prior and prior[0]!=signature:raise RuntimeError('Memory embedding backend changed; explicit rebuild required')
    if not prior:
        db.execute('INSERT INTO logis_backend VALUES(?)',(signature,));db.commit()
    query_vector=emb.embed_query(query)
    stored_vectors={}
    for sid,row in expected.items():
        if sid not in stored:
            mid=memory.remember(row['text'],source='logis-confirmed:'+sid,metadata=row,scope='session',extract=False,extract_entities=False,trust_tier='STATED')
            if not mid or failures:raise RuntimeError('Capture not vector verified')
            stored[sid]=(mid,row['revision'])
            db.execute('INSERT INTO logis_sources VALUES(?,?,?)',(sid,mid,row['revision']));db.commit()
        mid=stored[sid][0]
        vector=db.execute('SELECT embedding_json,model FROM memory_embeddings WHERE memory_id=?',(mid,)).fetchone()
        if not vector or vector[1]!=MODEL or len(json.loads(vector[0]))!=768:raise RuntimeError('Stored vector missing')
        decoded=np.array(json.loads(vector[0]),dtype=np.float32)
        if not np.isfinite(decoded).all() or not np.isclose(np.linalg.norm(decoded),1,atol=.02):raise RuntimeError('Invalid stored vector')
        stored_vectors[mid]=decoded
    hits=memory.recall(query,top_k=5,vec_weight=.65,fts_weight=.30,importance_weight=.05)
    if failures:raise RuntimeError('Vector recall unavailable')
    by_id={value[0]:expected[sid] for sid,value in stored.items()};matches=[];budget=6000
    method='mnemosyne_hybrid'
    if not hits:
        # SDK working-memory lexical gating can discard semantic paraphrases.
        # Match existing Logis cosine semantics using only verified sidecar vectors;
        # label this explicitly, and never substitute keyword-only results.
        ranked=sorted(((float(v@query_vector),mid) for mid,v in stored_vectors.items()),reverse=True)
        hits=[{'id':mid,'score':score,'dense_score':score} for score,mid in ranked[:5] if score>=.60]
        method='local_nomic_dense_fallback'
    for hit in hits:
        row=by_id.get(hit['id'])
        canonical=memory.get(hit['id'])
        if not row or not canonical or canonical['content']!=row['text'] or len(row['text'])>budget:continue
        matches.append({**row,'score':hit.get('score',0),'dense_score':hit.get('dense_score',0)});budget-=len(row['text'])
    memory.beam.conn.close();db.close()
    return {'status':'ready','matches':matches,'captured':len(stored),'calls':calls,'model':MODEL,'dimension':768,'method':method}

def locked_execute(request,base,vendor):
    import re,msvcrt
    if not re.fullmatch('[a-f0-9]{12}',request['project']):raise ValueError('Invalid project')
    data=pathlib.Path(base)/request['project'];data.mkdir(parents=True,exist_ok=True)
    if data.is_symlink() or (data/'operation.lock').is_symlink():raise ValueError('Unsafe worker path')
    with (data/'operation.lock').open('a+b') as lock:
        if lock.seek(0,2)==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:return execute(request,base,vendor)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':
    started=time.monotonic()
    try:
        raw=sys.stdin.buffer.read(200001)
        if len(raw)>200000:raise ValueError('Request too large')
        value=locked_execute(json.loads(raw),pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]))
    except Exception:
        value={'status':'unavailable','matches':[],'message':'Optional memory could not be vector-verified; no Mnemosyne recall was supplied.'}
    try:
        import ctypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('peak','working','p1','p2','p3','p4','p5','p6')]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(counters),counters.cb):value['peak_working_set_bytes']=counters.peak
    except Exception:pass
    value['worker_seconds']=round(time.monotonic()-started,3)
    print(json.dumps(value,ensure_ascii=False))
