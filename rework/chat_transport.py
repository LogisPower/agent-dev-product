"""Internal SSE reader with a total deadline; UI still receives a saved reply once complete."""
import http.client,json,socket,time,threading
from local_model_config import HOST, PORT, ALIAS, MAX_OUTPUT, REQUEST_SECONDS
class ResponseDeadline(TimeoutError):pass
class IncompleteReply(ValueError):pass
def completion(messages,timeout=REQUEST_SECONDS,json_output=False,host=HOST,port=PORT,canceled=None):
 from provider_cancel import current,ProviderCanceled
 canceled=canceled or current.get()
 if canceled():raise ProviderCanceled('Canceled before provider dispatch')
 if not 0<timeout<=REQUEST_SECONDS:raise ValueError('Deadline outside configured request bound')
 deadline=time.monotonic()+timeout
 def remaining():
  n=deadline-time.monotonic()
  if n<=0:raise ResponseDeadline('Local reply exceeded its total deadline')
  return n
 connection=http.client.HTTPConnection(host,port,timeout=min(5,remaining()));sock=None;timer=None;expired=threading.Event()
 stopped=threading.Event();cancel_seen=threading.Event()
 def cancellation_monitor():
  while not stopped.wait(0.25):
   try:requested=canceled()
   except Exception:requested=True # Revoked/unreadable scope fails closed.
   if requested:
    cancel_seen.set()
    active=sock or connection.sock
    if active is not None:
     try:active.shutdown(socket.SHUT_RDWR)
     except OSError:pass
    return
 monitor=threading.Thread(target=cancellation_monitor,daemon=True);monitor.start()
 try:
  options={'messages':messages,'temperature':0.3,'max_tokens':MAX_OUTPUT,'model':ALIAS,'stream':True}
  if json_output:options['response_format']={'type':'json_object'}
  connection.request('POST','/v1/chat/completions',body=json.dumps(options).encode(),headers={'Content-Type':'application/json','Accept':'text/event-stream'})
  sock=connection.sock
  if cancel_seen.is_set():raise ProviderCanceled('Canceled during provider dispatch')
  def abort():
   expired.set()
   try:sock.shutdown(socket.SHUT_RDWR)
   except OSError:pass
  timer=threading.Timer(remaining(),abort);timer.daemon=True;timer.start()
  sock.settimeout(remaining());response=connection.getresponse()
  if response.status!=200:raise RuntimeError('Local model returned non-success status')
  if 'text/event-stream' not in response.getheader('Content-Type',''):raise IncompleteReply('Expected local event stream')
  parts=[];size=0;wire=0;finish=None
  while True:
   sock.settimeout(remaining());line=response.readline(65537);remaining()
   if not line:raise IncompleteReply('Local stream disconnected before completion')
   wire+=len(line)
   if len(line)>65536 or wire>1000000:raise IncompleteReply('Local stream exceeds bounds')
   if not line.startswith(b'data:'):continue
   value=line[5:].strip()
   if value==b'[DONE]':
    if finish!='stop':raise IncompleteReply('Local answer did not finish normally')
    answer=''.join(parts)
    if not answer.strip():raise IncompleteReply('Empty local answer')
    if cancel_seen.is_set() or canceled():raise ProviderCanceled('Canceled; late provider answer rejected')
    return answer
   data=json.loads(value)
   if data.get('error'):raise IncompleteReply('Local generation failed')
   choices=data.get('choices',[])
   if not choices:continue
   choice=choices[0];part=choice.get('delta',{}).get('content')
   if part is not None:
    if not isinstance(part,str):raise IncompleteReply('Invalid local content')
    size+=len(part)
    if size>64000:raise IncompleteReply('Local content exceeds bound')
    parts.append(part)
    if not json_output:
     from answer_stream import emit_content
     emit_content(part)
   if choice.get('finish_reason') is not None:finish=choice['finish_reason']
 except (socket.timeout,TimeoutError) as e:
  if cancel_seen.is_set():raise ProviderCanceled('Provider request socket canceled') from e
  raise ResponseDeadline('Local reply exceeded its total deadline') from e
 except Exception as e:
  if cancel_seen.is_set():raise ProviderCanceled('Provider request socket canceled; slot release requires observation') from e
  if expired.is_set():raise ResponseDeadline('Local reply exceeded its total deadline') from e
  raise
 finally:
  stopped.set();monitor.join(timeout=1)
  if timer is not None:timer.cancel()
  if sock is not None:
   try:sock.shutdown(socket.SHUT_RDWR)
   except OSError:pass
  connection.close()
