"""One pinned STDIO server; no caller-selected executable, arguments or tools."""
import datetime,hashlib,json,os,queue,subprocess,threading,time
from pathlib import Path
RUNTIME=Path(r'C:\Users\LOGIS_USER\Documents\Codex\2026-10-23\task-2\rework-integration\bonsai-coordination\mcp-sdk-runtime-v2\Scripts\python.exe')
SERVER=Path(__file__).with_name('logis_mcp_server.py')
SERVER_SHA='530662a6428b19ab755dec07de843467a8b0dd04d0cb47fc3826eb59de080263'
PROTOCOL='2025-06-18'
TRACING=('LANGCHAIN_TRACING','LANGCHAIN_TRACING_V2','LANGSMITH_TRACING','LANGCHAIN_API_KEY','LANGSMITH_API_KEY')
class MCPUnavailable(RuntimeError):pass

def configured():return RUNTIME.is_file() and SERVER.is_file()
def privacy():
 if any(os.environ.get(k) for k in TRACING):raise MCPUnavailable('ambient_tracing_disabled')
def call_clock(canceled=lambda:False,*,timeout=12):
 privacy()
 if canceled():raise MCPUnavailable('cancelled')
 if not configured():raise MCPUnavailable('runtime_unavailable')
 if hashlib.sha256(SERVER.read_bytes()).hexdigest()!=SERVER_SHA:raise MCPUnavailable('server_integrity')
 if timeout<=0 or timeout>12:raise ValueError('Invalid MCP deadline')
 began=time.monotonic();deadline=began+timeout;inbox=queue.Queue(maxsize=8);overflow=threading.Event()
 env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','SYSTEMDRIVE','TEMP','TMP')}
 proc=subprocess.Popen([str(RUNTIME),'-I','-B',str(SERVER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 def reader():
  total=0
  try:
   while True:
    line=proc.stdout.readline(32769);total+=len(line)
    if len(line)>32768 or total>65536:overflow.set();return
    try:inbox.put_nowait(line)
    except queue.Full:overflow.set();return
    if not line:return
  except (OSError,ValueError):overflow.set()
 thread=threading.Thread(target=reader,name='logis-mcp-stdio',daemon=True);thread.start()
 transcript=[]
 def check():
  if canceled():raise MCPUnavailable('cancelled')
  if time.monotonic()>=deadline:raise MCPUnavailable('deadline')
  if overflow.is_set():raise MCPUnavailable('output_budget')
 def send(value):
  check();wire=json.dumps(value,separators=(',',':')).encode()+b'\n'
  if len(wire)>2048:raise MCPUnavailable('input_budget')
  proc.stdin.write(wire);proc.stdin.flush()
 def request(ident,method,params):
  send({'jsonrpc':'2.0','id':ident,'method':method,'params':params})
  while True:
   check()
   try:line=inbox.get(timeout=min(.05,max(.001,deadline-time.monotonic())))
   except queue.Empty:continue
   if not line:raise MCPUnavailable('server_exit')
   try:msg=json.loads(line)
   except (ValueError,UnicodeError):raise MCPUnavailable('invalid_json') from None
   if not isinstance(msg,dict) or msg.get('jsonrpc')!='2.0':raise MCPUnavailable('invalid_protocol')
   if 'id' not in msg:continue
   if type(msg['id']) is not int or msg['id']!=ident:raise MCPUnavailable('response_identity')
   if 'error' in msg:raise MCPUnavailable('rpc_error')
   result=msg.get('result')
   if not isinstance(result,dict):raise MCPUnavailable('invalid_result')
   check();transcript.append({'method':method,'status':'received','elapsed_seconds':round(time.monotonic()-began,3)})
   return result
 try:
  init=request(1,'initialize',{'protocolVersion':PROTOCOL,'capabilities':{},'clientInfo':{'name':'Logis','version':'1.0.0'}})
  if init.get('protocolVersion')!=PROTOCOL or 'tools' not in init.get('capabilities',{}):raise MCPUnavailable('negotiation_failed')
  send({'jsonrpc':'2.0','method':'notifications/initialized'})
  listed=request(2,'tools/list',{})
  tools=listed.get('tools',[])
  if len(tools)!=1 or tools[0].get('name')!='clock_snapshot' or tools[0].get('inputSchema',{}).get('properties',{})!={}:raise MCPUnavailable('tool_contract_changed')
  value=request(3,'tools/call',{'name':'clock_snapshot','arguments':{}})
  if value.get('isError'):raise MCPUnavailable('tool_error')
  result=value.get('structuredContent')
  if not isinstance(result,dict):raise MCPUnavailable('structured_result_missing')
  if set(result)!={'utc','host_time','host_timezone','source','accuracy','effect'}:raise MCPUnavailable('result_schema')
  if result['effect']!='none' or result['source']!='host system clock':raise MCPUnavailable('result_schema')
  try:stamp=datetime.datetime.fromisoformat(result['utc'])
  except (ValueError,TypeError):raise MCPUnavailable('invalid_timestamp') from None
  if stamp.utcoffset()!=datetime.timedelta(0) or abs((datetime.datetime.now(datetime.timezone.utc)-stamp).total_seconds())>15:raise MCPUnavailable('stale_timestamp')
  check()
  return {'result':result,'protocol':PROTOCOL,'server':{'name':init.get('serverInfo',{}).get('name'),'version':init.get('serverInfo',{}).get('version'),'sdk':'2.3.0'},'transport':'stdio','calls':transcript,'seconds':round(time.monotonic()-began,3),'langchain':'StructuredTool','network_listener':False}
 finally:
  try:
   proc.stdin.close()
   try:proc.wait(timeout=.5)
   except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=1)
  except (OSError,subprocess.TimeoutExpired):raise MCPUnavailable('cleanup_failed') from None
  finally:
   thread.join(timeout=1)
   proc.stdout.close()
  if thread.is_alive():raise MCPUnavailable('reader_cleanup_failed')

def invoke_clock(canceled=lambda:False):
 privacy()
 from langchain_core.tools import StructuredTool
 from pydantic import BaseModel,ConfigDict
 class Empty(BaseModel):model_config=ConfigDict(extra='forbid')
 def invoke():
  privacy()
  return call_clock(canceled)
 tool=StructuredTool.from_function(func=invoke,name='mcp_clock',description='Read host clock through the pinned local MCP server.',args_schema=Empty)
 return tool.invoke({},config={'callbacks':[],'tags':[],'metadata':{}})
