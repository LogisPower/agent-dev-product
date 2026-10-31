"""Windows scoped file operations with pinned paths and explicit recovery receipts.

No UAC/ACL changes. Server constructs one exact approved root, never model input.
Move is copy-verify-delete-by-handle, not atomic; interrupted outcomes are journaled.
"""
import os,json,hashlib,uuid,re,ctypes,contextlib,threading
from pathlib import Path,PureWindowsPath
from ctypes import wintypes as W

MAX_BYTES=131072
def digest(raw):return hashlib.sha256(raw).hexdigest()
def relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or len(value)>180:raise ValueError('Use a bounded relative forward-slash path')
    parts=value.split('/')
    for x in parts:
        if x.casefold() in ('','.','..','.logis') or x[-1:] in (' ','.') or re.search(r'[<>"|?*\x00-\x1f]',x) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',x):raise ValueError('Unsafe or reserved path')
    return parts

class WinIO:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('Windows adapter unavailable')
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.k.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE];self.k.CreateFileW.restype=W.HANDLE
        self.k.GetFinalPathNameByHandleW.argtypes=[W.HANDLE,W.LPWSTR,W.DWORD,W.DWORD];self.k.GetFinalPathNameByHandleW.restype=W.DWORD
        for name,args in {'CloseHandle':[W.HANDLE],'GetFileInformationByHandleEx':[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD], 'ReadFile':[W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p], 'WriteFile':[W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p], 'SetFilePointerEx':[W.HANDLE,ctypes.c_longlong,ctypes.c_void_p,W.DWORD],'SetEndOfFile':[W.HANDLE], 'FlushFileBuffers':[W.HANDLE], 'SetFileInformationByHandle':[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD]}.items():
            getattr(self.k,name).argtypes=args;getattr(self.k,name).restype=W.BOOL
    def check(self,ok):
        if not ok:raise ctypes.WinError(ctypes.get_last_error())
    @contextlib.contextmanager
    def opened(self,path,*,directory=False,create=False,change=False,lock=False):
        access=0x80000000 | (0x40000000|0x10000 if change else 0)
        handle=self.k.CreateFileW(str(path),access,1 if directory else 0,None,4 if lock else (1 if create else 3),0x00200000|(0x02000000 if directory else 0),None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            data=(W.DWORD*2)();self.check(self.k.GetFileInformationByHandleEx(handle,9,ctypes.byref(data),ctypes.sizeof(data)))
            if data[0]&0x400 or bool(data[0]&0x10)!=directory:raise ValueError('Reparse point or unexpected object type rejected')
            actual=ctypes.create_unicode_buffer(32768);n=self.k.GetFinalPathNameByHandleW(handle,actual,len(actual),0)
            if not 0<n<len(actual):raise ValueError('Unable to verify canonical handle path')
            resolved=actual.value.removeprefix('\\\\?\\')
            if os.path.normcase(os.path.abspath(resolved))!=os.path.normcase(os.path.abspath(path)):
                raise ValueError('Filesystem alias rejected; use canonical long path')
            if not directory:
                class Standard(ctypes.Structure):
                    _fields_=[('allocated',ctypes.c_longlong),('end',ctypes.c_longlong),('links',W.DWORD),('delete_pending',ctypes.c_ubyte),('directory',ctypes.c_ubyte)]
                standard=Standard();self.check(self.k.GetFileInformationByHandleEx(handle,1,ctypes.byref(standard),ctypes.sizeof(standard)))
                if standard.links!=1:raise ValueError('Hard-linked file rejected')
            yield handle
        finally:self.k.CloseHandle(handle)
    def read(self,h):
        self.check(self.k.SetFilePointerEx(h,0,None,0));buf=ctypes.create_string_buffer(MAX_BYTES+1);n=W.DWORD()
        self.check(self.k.ReadFile(h,buf,MAX_BYTES+1,ctypes.byref(n),None))
        if n.value>MAX_BYTES:raise ValueError('File exceeds workspace read/edit bound')
        return buf.raw[:n.value]
    def write(self,h,raw):
        self.check(self.k.SetFilePointerEx(h,0,None,0));n=W.DWORD();buf=ctypes.create_string_buffer(raw)
        self.check(self.k.WriteFile(h,buf,len(raw),ctypes.byref(n),None))
        if n.value!=len(raw):raise OSError('Partial write; inspect recovery record')
        self.check(self.k.SetEndOfFile(h));self.check(self.k.FlushFileBuffers(h))
    def delete_open_file(self,h):
        flag=W.BOOL(True);self.check(self.k.SetFileInformationByHandle(h,4,ctypes.byref(flag),ctypes.sizeof(flag)))
    def publish(self,path,record):
        # Append-only, checksummed transitions avoid replacing a file while Windows
        # directory handles intentionally deny rename. Partial versions are ignored;
        # previously flushed transitions are never rewritten or removed.
        from journal_contract import validate_record,validate_history,digest as record_digest
        prior,records,errors=self.journal(path)
        if errors:raise ValueError('Damaged journal cannot accept another transition')
        record=dict(record)
        record.update(journal_version=2,sequence=len(records),previous=record_digest(prior) if prior else None)
        validate_record(record,path.stem,relative);validate_history(records+[record])
        raw=json.dumps(record,sort_keys=True).encode()
        version=path.with_name(path.stem+'.'+uuid.uuid4().hex+'.version')
        envelope=json.dumps({'record':record,'sha256':digest(raw)},sort_keys=True).encode()
        with self.opened(version,create=True,change=True) as h:
            self.write(h,envelope)
            if self.read(h)!=envelope:raise OSError('Journal version verification failed')
    def journal(self,path):
        from journal_contract import validate_record,validate_history
        records=[];errors=[]
        paths=[path]+sorted(path.parent.glob(path.stem+'.*.version'))
        if len(paths)>17:raise ValueError('Unexpected journal version count; inspect manually')
        for p in paths:
            try:
                with self.opened(p) as h:value=json.loads(self.read(h))
                if p.suffix=='.version':
                    raw=json.dumps(value['record'],sort_keys=True).encode()
                    if digest(raw)!=value['sha256']:raise ValueError('Journal checksum mismatch')
                    value=value['record']
                validate_record(value,path.stem,relative)
                records.append(value)
            except FileNotFoundError:pass
            except (OSError,ValueError,KeyError,TypeError) as e:errors.append({'file':p.name,'error_type':type(e).__name__})
        latest=validate_history(records)
        return latest,records,errors

class Workspace:
    def __init__(self,root):
        self.root=Path(root).absolute();self.io=WinIO();self.lock=threading.Lock()
        # Creation/provisioning is explicit outside this constructor.
        if not self.root.is_dir():raise ValueError('Approved workspace must be provisioned first')
    @contextlib.contextmanager
    def pinned(self,rel):
        parts=relative(rel)
        with contextlib.ExitStack() as stack:
            # Deny write/delete sharing on every ancestor while using its path.
            for p in reversed([self.root,*self.root.parents]):stack.enter_context(self.io.opened(p,directory=True))
            parent=self.root
            for part in parts[:-1]:
                parent=parent/part;stack.enter_context(self.io.opened(parent,directory=True))
            yield parent/parts[-1]
    def read(self,name):
        with self.pinned(name) as p,self.io.opened(p) as h:raw=self.io.read(h)
        return {'path':name,'content':raw.decode('utf-8'),'sha256':digest(raw),'bytes':len(raw)}
    def inspect(self,request_id):
        """Read-only reconciliation: never replay, restore or rewrite an effect."""
        if not re.fullmatch('[a-f0-9]{32}',request_id):raise ValueError('Stable request ID required')
        journal=self.root/'.logis';records=[];errors=[];current=None
        with self.lock,contextlib.ExitStack() as stack:
            for p in reversed([journal,*journal.parents]):stack.enter_context(self.io.opened(p,directory=True))
            current,records,errors=self.io.journal(journal/(request_id+'.json'))
            if not records:return {'request_id':request_id,'state':'unavailable','errors':errors,'automatic_replay':False}
            hashes={x.get('request_hash') for x in records}
            if len(hashes)!=1 or None in hashes:return {'request_id':request_id,'state':'conflicting_receipts','automatic_replay':False,'errors':errors}
            record=current or max(records,key=lambda x:('prepared','mutation_started','verified').index(x['status']))
            observed={}
            for key in ('path','destination'):
                if record.get(key):
                    try:
                        value=self.read(record[key]);observed[key]={'exists':True,'sha256':value['sha256'],'bytes':value['bytes']}
                    except FileNotFoundError:observed[key]={'exists':False}
                    except (OSError,ValueError) as e:observed[key]={'unknown':True,'error_type':type(e).__name__}
            matches=(observed.get('path',{}).get('sha256')==record.get('new_hash')) if record['operation']!='move' else (observed.get('path',{}).get('exists') is False and observed.get('destination',{}).get('sha256')==record.get('expected'))
            backup_present=False
            if str(record.get('backup','')).replace('\\','/')=='.logis/'+request_id+'.before':
                try:
                    with self.io.opened(journal/(request_id+'.before')) as h:backup_present=digest(self.io.read(h))==record.get('expected')
                except (OSError,ValueError):pass
            return {'request_id':request_id,'state':'verified_effect_observed' if current and current['status']=='verified' and matches and not errors else 'needs_owner_reconciliation',
              'receipt':record,'valid_transition_available':current is not None,'preserved_versions':len(records),'observed':observed,
              'original_recovery_verified':backup_present,'errors':errors,'automatic_replay':False,
              'next_action':'Inspect this evidence before any separately approved restore. Do not retry with a new request ID.'}
    def mutate(self,operation,name,*,request_id,content=None,expected_sha256=None,destination=None):
        if operation not in ('create','edit','move'):raise ValueError('Unsupported workspace operation')
        if not re.fullmatch('[a-f0-9]{32}',request_id):raise ValueError('Stable request ID required')
        relative(name)
        if operation=='move':
            relative(destination)
            if destination.casefold()==name.casefold():raise ValueError('Distinct move destination required')
        if operation in ('create','edit'):
            if not isinstance(content,str):raise ValueError('Explicit UTF-8 text required')
            raw=content.encode('utf-8')
            if len(raw)>MAX_BYTES:raise ValueError('Content exceeds bound')
        if operation!='create' and not re.fullmatch('[a-f0-9]{64}',expected_sha256 or ''):raise ValueError('Expected source hash required')
        contract={'operation':operation,'path':name,'destination':destination,'expected':expected_sha256,'new_hash':digest(raw) if operation!='move' else None}
        key=digest(json.dumps(contract,sort_keys=True).encode())
        # Journal is a reserved user-owned directory, provisioned explicitly.
        journal=self.root/'.logis';receipt=journal/(request_id+'.json');backup=journal/(request_id+'.before')
        with self.lock,contextlib.ExitStack() as guard,contextlib.ExitStack() as stack:
            for p in reversed([journal,*journal.parents]):stack.enter_context(self.io.opened(p,directory=True))
            # Cross-process exclusion lasts through final publication. No stale
            # lock deletion is necessary: Windows releases the handle on exit.
            guard.enter_context(self.io.opened(journal/(request_id+'.lock'),change=True,lock=True))
            prior,versions,journal_errors=self.io.journal(receipt)
            if journal_errors:raise ValueError('Damaged journal needs inspection; no automatic replay')
            if prior:
                if prior['request_hash']!=key:raise ValueError('Request ID reused for different change')
                if prior['status']!='verified':raise ValueError('Prior outcome needs reconciliation; no automatic replay')
                return {**prior,'replayed':True}
            record={'request_hash':key,**contract,'status':'prepared','request_id':request_id,'replayed':False}
            self.io.publish(receipt,record)
            try:
                path=stack.enter_context(self.pinned(name))
                if operation=='create':
                    handle=stack.enter_context(self.io.opened(path,create=True,change=True));self.io.write(handle,raw)
                    if self.io.read(handle)!=raw:raise OSError('Create verification failed')
                else:
                    handle=stack.enter_context(self.io.opened(path,change=True));before=self.io.read(handle)
                    if digest(before)!=expected_sha256:raise ValueError('Source changed; no file mutation')
                    with self.io.opened(backup,create=True,change=True) as bh:
                        self.io.write(bh,before)
                        if self.io.read(bh)!=before:raise OSError('Recovery copy verification failed')
                    record['backup']=backup.relative_to(self.root).as_posix()
                    record['status']='mutation_started';self.io.publish(receipt,record)
                    if operation=='edit':
                        self.io.write(handle,raw)
                        if self.io.read(handle)!=raw:raise OSError('Edit verification failed')
                    else:
                        target=stack.enter_context(self.pinned(destination))
                        with self.io.opened(target,create=True,change=True) as th:
                            self.io.write(th,before)
                            if self.io.read(th)!=before:raise OSError('Move copy verification failed')
                        self.io.delete_open_file(handle)
                # Close source before claiming delete-on-close completed.
                stack.close()
                record['status']='verified'
                # Re-pin journal before committing final receipt.
                with contextlib.ExitStack() as final:
                    for p in reversed([journal,*journal.parents]):final.enter_context(self.io.opened(p,directory=True))
                    saved,versions,errors=self.io.journal(receipt)
                    if errors or not saved or saved.get('request_hash')!=key or saved.get('status') not in ('prepared','mutation_started'):
                        raise ValueError('Receipt changed; reconcile effect before finalization')
                    self.io.publish(receipt,record)
                return record
            except Exception:
                # Prepared/mutation_started survives; never blindly retry partial moves.
                raise
