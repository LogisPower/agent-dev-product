"""Local SearXNG discovery; page fetching stays with the protected downloader."""
import ipaddress,json,re,time,urllib.request,urllib.parse,urllib.error,subprocess,sys,os
from pathlib import Path

ENDPOINT='http://127.0.0.1:8891/search'
MAX_BYTES=262144

CODES={'deadline','cancelled','response_budget','invalid_response','invalid_json','unexpected_http_response','connection_failure','transport_timeout','worker_failure','worker_output_budget','cleanup_failure'}
class SearchUnavailable(RuntimeError):
 def __init__(self,code,http_status=None):
  if code not in CODES:code='worker_failure'
  self.code=code
  self.http_status=http_status if type(http_status) is int and 100<=http_status<=599 else None
  super().__init__(code)
 def diagnostic(self):
  result={'code':self.code}
  if self.http_status is not None:result['http_status']=self.http_status
  return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def safe_lead(url):
 try:
  p=urllib.parse.urlsplit(url)
  if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:return False
  if p.port not in (None,80,443):return False
  host=p.hostname.casefold().rstrip('.')
  if host=='localhost' or '.' not in host or host.endswith(('.localhost','.local','.internal')):return False
  try:return ipaddress.ip_address(host).is_global
  except ValueError:return True
 except (ValueError,TypeError):return False

def parse_results(value,limit):
 if not isinstance(value,dict) or not isinstance(value.get('results'),list):raise SearchUnavailable('invalid_response')
 rows=[];seen=set()
 for item in value['results'][:100]:
  if not isinstance(item,dict):continue
  url=item.get('url');title=item.get('title');snippet=item.get('content','')
  if not isinstance(url,str) or len(url)>2048 or not safe_lead(url) or not isinstance(title,str) or not isinstance(snippet,str):continue
  if url in seen:continue
  seen.add(url);rows.append({'url':url,'title':title[:300],'snippet':snippet[:1500]})
  if len(rows)>=limit:break
 errors=value.get('unresponsive_engines',[])
 # Do not propagate raw engine exceptions, cookies, headers or arbitrary HTML.
 return {'results':rows,'provider':'local_searxng','partial':bool(errors),'unresponsive_engine_count':len(errors) if isinstance(errors,list) else None}

def _fetch(query,limit=8,opener=None):
 if type(query) is not str or not 1<=len(query.strip())<=500:raise ValueError('Explicit public query required')
 if type(limit) is not int or not 1<=limit<=8:raise ValueError('Search limit must be 1..8')
 # Defense in depth. Callers still enforce public-only exact user excerpts.
 if re.search(r'(?i)(password|api.?key|access.?token|private.?key|secret|bearer\s|\bsk-[a-z0-9]|\b[A-Z]:\\|[\w.+-]+@[\w.-]+\.[a-z]{2,})',query):raise ValueError('Private query rejected')
 body=urllib.parse.urlencode({'q':query.strip(),'format':'json','categories':'general','language':'en','pageno':1}).encode()
 req=urllib.request.Request(ENDPOINT,data=body,headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},method='POST')
 client=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 started=time.monotonic()
 try:
  with client.open(req,timeout=12) as response:
   if response.status!=200:raise SearchUnavailable('unexpected_http_response',response.status)
   if response.headers.get_content_type()!='application/json':raise SearchUnavailable('unexpected_http_response')
   raw=response.read(MAX_BYTES+1)
   if len(raw)>MAX_BYTES:raise SearchUnavailable('response_budget')
   result=parse_results(json.loads(raw),limit)
 except urllib.error.HTTPError as error:
  raise SearchUnavailable('unexpected_http_response',error.code) from None
 except (json.JSONDecodeError,UnicodeError):raise SearchUnavailable('invalid_json') from None
 except TimeoutError:raise SearchUnavailable('transport_timeout') from None
 except OSError:raise SearchUnavailable('connection_failure') from None
 result['seconds']=round(time.monotonic()-started,3)
 return result


def _owned_request(query,limit,cancel=None,*,popen=subprocess.Popen,monotonic=time.monotonic):
 """12s total transaction deadline plus <=1s owned-process reap budget.

 The child alone owns transport. Kill+wait closes its sockets even if headers,
 body trickles, or parsing block. No background thread or automatic retry.
 """
 started=monotonic();deadline=started+12
 if cancel and cancel():raise SearchUnavailable('cancelled')
 proc=popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 pending=json.dumps({'query':query,'limit':limit},ensure_ascii=False).encode('utf-8')
 try:
  while True:
   if cancel and cancel():raise SearchUnavailable('cancelled')
   remaining=deadline-monotonic()
   if remaining<=0:raise SearchUnavailable('deadline')
   try:
    out,_=proc.communicate(input=pending,timeout=min(.1,remaining));pending=None
    break
   except subprocess.TimeoutExpired:pending=None
  if cancel and cancel():raise SearchUnavailable('cancelled')
  if monotonic()>=deadline:raise SearchUnavailable('deadline')
  if proc.returncode!=0:raise SearchUnavailable('worker_failure')
  if len(out)>32768:raise SearchUnavailable('worker_output_budget')
  try:message=json.loads(out)
  except (ValueError,UnicodeError):raise SearchUnavailable('invalid_response') from None
  if not isinstance(message,dict):raise SearchUnavailable('invalid_response')
  if 'error' in message:
   e=message['error']
   if not isinstance(e,dict):raise SearchUnavailable('invalid_response')
   raise SearchUnavailable(e.get('code'),e.get('http_status'))
  result=message.get('result')
  if not isinstance(result,dict) or not isinstance(result.get('results'),list):raise SearchUnavailable('invalid_response')
  if monotonic()>=deadline:raise SearchUnavailable('deadline')
  result['seconds']=round(monotonic()-started,3)
  return result
 finally:
  # This is exclusively the child launched above, never another process/PID.
  try:
   if proc.poll() is None:proc.kill()
   proc.wait(timeout=1)
  except (OSError,subprocess.TimeoutExpired):raise SearchUnavailable('cleanup_failure') from None
  finally:
   for stream in (proc.stdin,proc.stdout):
    if stream:stream.close()

def search_web(_context,query,limit=8,cancel=None):
 if type(query) is not str or not 1<=len(query.strip())<=500:raise ValueError('Explicit public query required')
 if type(limit) is not int or not 1<=limit<=8:raise ValueError('Search limit must be 1..8')
 if re.search(r'(?i)(password|api.?key|access.?token|private.?key|secret|bearer\s|\bsk-[a-z0-9]|\b[A-Z]:\\|[\w.+-]+@[\w.-]+\.[a-z]{2,})',query):raise ValueError('Private query rejected')
 return _owned_request(query,limit,cancel)

def _worker():
 try:
  raw=sys.stdin.buffer.read(4097)
  if len(raw)>4096:raise SearchUnavailable('invalid_response')
  payload=json.loads(raw);result={'result':_fetch(payload['query'],payload['limit'])}
 except SearchUnavailable as error:result={'error':error.diagnostic()}
 except Exception:result={'error':{'code':'worker_failure'}}
 wire=json.dumps(result,ensure_ascii=True,allow_nan=False).encode('utf-8')
 if len(wire)>32768:wire=b'{"error":{"code":"worker_output_budget"}}'
 sys.stdout.buffer.write(wire)

if __name__=='__main__':
 if sys.argv[1:]!=['--worker']:raise SystemExit(2)
 _worker()
