"""One fixed PDH query; five measured intervals, no shell or third-party imports.

Only executed by the scoped parent, in its own killable normal-user process.
No arbitrary counter arguments, descendants, files, logging or persistent loop.
"""
import ctypes,datetime,json,math,sys,time
from ctypes import wintypes as W

PATHS=(r'\LogicalDisk(C:)\% Idle Time',r'\LogicalDisk(C:)\Avg. Disk sec/Read',r'\LogicalDisk(C:)\Avg. Disk sec/Write',
       r'\LogicalDisk(C:)\Current Disk Queue Length',r'\LogicalDisk(C:)\Disk Read Bytes/sec',r'\LogicalDisk(C:)\Disk Write Bytes/sec',
       r'\Memory\Available MBytes',r'\Memory\Pages Input/sec',r'\Memory\Pages Output/sec')

class NativeFailure(Exception):pass
class Number(ctypes.Union):
    _fields_=[('longValue',ctypes.c_long),('doubleValue',ctypes.c_double),('largeValue',ctypes.c_longlong),('AnsiStringValue',ctypes.c_char_p),('WideStringValue',ctypes.c_wchar_p)]
class Formatted(ctypes.Structure):
    _anonymous_=('value',)
    _fields_=[('CStatus',W.DWORD),('value',Number)]

class PDH:
    def __init__(self):
        self.lib=ctypes.WinDLL('pdh.dll');self.query=W.HANDLE();self.handles=[]
        for name,args in [('PdhOpenQueryW',[W.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(W.HANDLE)]),
                          ('PdhAddEnglishCounterW',[W.HANDLE,W.LPCWSTR,ctypes.c_size_t,ctypes.POINTER(W.HANDLE)]),
                          ('PdhCollectQueryData',[W.HANDLE]),
                          ('PdhGetFormattedCounterValue',[W.HANDLE,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.POINTER(Formatted)]),
                          ('PdhCloseQuery',[W.HANDLE])]:
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=W.LONG
    def check(self,status,stage):
        if status!=0:raise NativeFailure(stage+'_'+format(status & 0xffffffff,'08x'))
    def open(self):
        self.check(self.lib.PdhOpenQueryW(None,0,ctypes.byref(self.query)),'open')
        for path in PATHS:
            counter=W.HANDLE();self.check(self.lib.PdhAddEnglishCounterW(self.query,path,0,ctypes.byref(counter)),'add_counter');self.handles.append(counter)
    def collect(self):self.check(self.lib.PdhCollectQueryData(self.query),'collect')
    def values(self):
        values=[]
        for handle in self.handles:
            value=Formatted()
            # Preserve raw overshoot for the separately reviewed evaluator.
            self.check(self.lib.PdhGetFormattedCounterValue(handle,0x200|0x8000,None,ctypes.byref(value)),'format')
            if value.CStatus not in (0,1):raise NativeFailure('counter_status_'+format(value.CStatus,'08x'))
            values.append((value.doubleValue,int(value.CStatus)))
        return values
    def close(self):
        if self.query:
            self.check(self.lib.PdhCloseQuery(self.query),'close');self.query=W.HANDLE()

def sample(backend_factory=PDH,monotonic=time.monotonic,sleep=time.sleep,utc=None):
    utc=utc or (lambda:datetime.datetime.now(datetime.timezone.utc).isoformat())
    begin=monotonic();backend=None;phase='initialize';rows=[];timings={};failure=None
    def budget():
        if monotonic()-begin>=10:raise NativeFailure('internal_deadline')
    try:
        backend=backend_factory();backend.open();budget();timings['initialize_seconds']=monotonic()-begin
        phase='prime';mark=monotonic();backend.collect();budget();timings['prime_seconds']=monotonic()-mark
        # One initial raw collection is intentionally excluded. All following
        # five measurements are retained regardless of their values.
        phase='measure';mark=monotonic()
        for _ in range(5):
            if monotonic()-begin+1>=10:raise NativeFailure('insufficient_interval_budget')
            sleep(1);backend.collect();budget();stamp=utc();values=backend.values();budget()
            if len(values)!=len(PATHS):raise NativeFailure('counter_count')
            counters=[]
            for path,(value,status) in zip(PATHS,values):
                if type(status) is not int or status not in (0,1) or type(value) not in (int,float) or not math.isfinite(value):raise NativeFailure('invalid_counter')
                counters.append({'Path':path,'CookedValue':value,'Status':0,'NativeStatus':status})
            rows.append({'timestamp':stamp,'counters':counters})
        timings['measurement_seconds']=monotonic()-mark
    except (NativeFailure,OSError,AttributeError) as error:
        failure={'phase':phase,'code':str(error) if isinstance(error,NativeFailure) else type(error).__name__}
    finally:
        if backend is not None:
            try:backend.close()
            except (NativeFailure,OSError):failure={'phase':'close','code':'native_cleanup_failed'}
    timings['worker_seconds']=monotonic()-begin
    return {'status':'unavailable' if failure else 'ok','records':[] if failure else rows,'failure':failure,'timings':timings,
            'source':'Windows PDH fixed English counters; one query, no PowerShell',
            'measurement':{'version':2,'warmup_samples_discarded':1,'measured_samples':5,'interval_seconds':1}}

if __name__=='__main__':
    if len(sys.argv)!=1:raise SystemExit('No arguments accepted')
    result=sample();wire=json.dumps(result,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(wire)>24000:wire=b'{"status":"unavailable","records":[],"failure":{"code":"output_budget"}}'
    sys.stdout.buffer.write(wire)
