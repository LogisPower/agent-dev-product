"""Trusted resident-process collector. No model execution, loading or stopping.

Full verification can hash identities. Resident attachment instead reuses the
prior hash receipt only for the same measured process, requiring no later file
modification and pinned read handles. It explicitly reports that weaker basis.
Lifetime is explicit; caller must close after releasing its inference ownership.
"""
import contextlib,ctypes,datetime,hashlib,json,socket,struct,time,urllib.request,re
from pathlib import Path
from ctypes import wintypes as W
from workspace_files import WinIO
from model_bridge import ModelUnavailable

class Memory(ctypes.Structure):
 _fields_=[('length',W.DWORD),('load',W.DWORD)]+[(x,ctypes.c_ulonglong) for x in ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended')]
class ProcessMemory(ctypes.Structure):
 _fields_=[('cb',W.DWORD),('faults',W.DWORD)]+[(x,ctypes.c_size_t) for x in ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
class TcpRow(ctypes.Structure):
 _fields_=[(x,W.DWORD) for x in ('state','address','port','remote_address','remote_port','pid')]

class CpuIdentityCollector:
 def __init__(self,measured):
  self.measured=json.loads(json.dumps(measured));self.stack=contextlib.ExitStack();self.io=WinIO();self.handle=None;self.verified=False
  root=Path(r'C:\Users\LOGIS_USER\Documents\Codex\2026-10-22\us\outputs\Local AI\Bonsai')
  paths=[str(root/'runtime/llama-server.exe'),str(root/'models/Ternary-Bonsai-2-9B-PQ2_0.gguf'),str(root/'models/Ternary-Bonsai-2-9B-mmproj-Q8_0.gguf')]
  expected=[paths[0],'-m',paths[1],'--mmproj',paths[2],'--alias','bonsai2-9b-vision','--device','none','-ngl','0','--no-kv-offload','--no-op-offload','--no-mmproj-offload','-c','2048','--parallel','1','--threads','2','--threads-batch','2','--host','127.0.0.1','--port','8082','--jinja','--reasoning-budget','0','--cors-origins','localhost']
  if measured.get('argv')!=expected or set(measured.get('identity',{}))!=set(paths) or type(measured.get('pid')) is not int or measured['pid']<1:
   raise ModelUnavailable('CPU receipt does not match the fixed approved local profile')
  if any(type(x.get('bytes')) is not int or x['bytes']<1 or not re.fullmatch('[a-f0-9]{64}',x.get('sha256','')) for x in measured['identity'].values()):
   raise ModelUnavailable('Invalid measured binary identity')
  self.k=ctypes.WinDLL('kernel32',use_last_error=True);self.ps=ctypes.WinDLL('psapi',use_last_error=True);self.ip=ctypes.WinDLL('iphlpapi',use_last_error=True)
  self.k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.k.OpenProcess.restype=W.HANDLE
  self.k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)];self.k.QueryFullProcessImageNameW.restype=W.BOOL
  self.k.GetProcessTimes.argtypes=[W.HANDLE,*([ctypes.POINTER(W.FILETIME)]*4)];self.k.GetProcessTimes.restype=W.BOOL
  self.k.GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(Memory)];self.k.GlobalMemoryStatusEx.restype=W.BOOL
  self.ps.GetProcessMemoryInfo.argtypes=[W.HANDLE,ctypes.POINTER(ProcessMemory),W.DWORD];self.ps.GetProcessMemoryInfo.restype=W.BOOL
  self.ip.GetExtendedTcpTable.argtypes=[ctypes.c_void_p,ctypes.POINTER(W.DWORD),W.BOOL,W.ULONG,ctypes.c_int,W.ULONG];self.ip.GetExtendedTcpTable.restype=W.DWORD
 def close(self):
  self.stack.close();self.handle=None;self.verified=False
 def _process(self):
  name=ctypes.create_unicode_buffer(32768);size=W.DWORD(len(name))
  self.io.check(self.k.QueryFullProcessImageNameW(self.handle,0,name,ctypes.byref(size)))
  times=[W.FILETIME() for _ in range(4)];self.io.check(self.k.GetProcessTimes(self.handle,*[ctypes.byref(x) for x in times]))
  created=((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)/10000000-11644473600
  start=datetime.datetime.strptime(self.measured['started_at'],'%Y%m%dT%H%M%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()
  if not start<=created<=start+120 or Path(name.value)!=Path(self.measured['argv'][0]):raise ModelUnavailable('Measured CPU process instance mismatch')
  return created
 def _listener(self):
  size=W.DWORD();code=self.ip.GetExtendedTcpTable(None,ctypes.byref(size),False,2,3,0)
  if code!=122 or not 4<=size.value<=1048576:raise ModelUnavailable('Listener ownership table unavailable')
  buf=ctypes.create_string_buffer(size.value);code=self.ip.GetExtendedTcpTable(buf,ctypes.byref(size),False,2,3,0)
  if code:raise ctypes.WinError(code)
  count=W.DWORD.from_buffer(buf).value
  if 4+count*ctypes.sizeof(TcpRow)>size.value:raise ModelUnavailable('Invalid listener table')
  rows=[TcpRow.from_buffer(buf,4+i*ctypes.sizeof(TcpRow)) for i in range(count)]
  own=[x for x in rows if socket.ntohs(x.port&65535)==8082]
  if len(own)!=1 or own[0].pid!=self.measured['pid'] or socket.inet_ntoa(struct.pack('=I',own[0].address))!='127.0.0.1':raise ModelUnavailable('CPU endpoint is not exclusively the measured loopback process')
 def open_verified(self,*,reuse_measured_resident=False):
  if self.verified:raise ModelUnavailable('Collector already opened')
  try:
   self.handle=self.k.OpenProcess(0x1000|0x10,False,self.measured['pid'])
   if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
   self.stack.callback(self.io.k.CloseHandle,self.handle);self._process();self._listener()
   for path,expected in self.measured['identity'].items():
    self.stack.enter_context(self.io.opened(Path(path)))
    if reuse_measured_resident:
     stat=Path(path).stat();start=datetime.datetime.strptime(self.measured['started_at'],'%Y%m%dT%H%M%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()
     if stat.st_size!=expected['bytes'] or stat.st_mtime>start:raise ModelUnavailable('Measured file changed or cannot reuse prior identity evidence')
    else:
     h=hashlib.sha256();length=0
     with open(path,'rb') as file:
      for block in iter(lambda:file.read(1024*1024),b''):h.update(block);length+=len(block)
     if length!=expected['bytes'] or h.hexdigest()!=expected['sha256']:raise ModelUnavailable('CPU model/projector/backend identity changed')
   self.identity_basis='same measured process, prior SHA256 receipt, unchanged size/mtime, pinned read handles; no fresh rehash' if reuse_measured_resident else 'fresh SHA256 and pinned read handles'
   self.verified=True;return self
  except Exception:self.close();raise
 def _get(self,path):
  with urllib.request.urlopen('http://127.0.0.1:8082'+path,timeout=3) as response:raw=response.read(262145)
  if len(raw)>262144:raise ModelUnavailable('CPU metadata size bound')
  return json.loads(raw)
 def __call__(self):
  if not self.verified:raise ModelUnavailable('CPU binary identities have not been pinned and verified')
  self._process();self._listener();props=self._get('/props');slots=self._get('/slots')
  if props.get('model_alias')!='bonsai2-9b-vision' or props.get('model_path')!=self.measured['argv'][2] or props.get('total_slots')!=1:raise ModelUnavailable('CPU endpoint model configuration mismatch')
  mem=Memory();mem.length=ctypes.sizeof(mem);self.io.check(self.k.GlobalMemoryStatusEx(ctypes.byref(mem)))
  proc=ProcessMemory();proc.cb=ctypes.sizeof(proc);self.io.check(self.ps.GetProcessMemoryInfo(self.handle,ctypes.byref(proc),ctypes.sizeof(proc)))
  return {'pid':self.measured['pid'],'process_start_verified':True,'identity':self.measured['identity'],'argv':self.measured['argv'],
   'identity_basis':self.identity_basis,
   'observed_at':time.time(),'context':props.get('default_generation_settings',{}).get('n_ctx'),
   'slots':[{k:x.get(k) for k in ('id','n_ctx','is_processing')} for x in slots],
   'available_ram_mib':mem.avail_phys/1048576,'commit_headroom_mib':mem.avail_page/1048576,'process_working_mib':proc.working/1048576}
