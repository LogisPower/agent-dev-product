"""Private, explicit device pairing. Secrets never stored in plaintext or logged."""
import hashlib,hmac,json,secrets,sqlite3,time,threading
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit

ORIGIN='https://logis.example.invalid'
COOKIE='__Host-logis_device'
TTL=30*24*3600
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
class Denied(Exception):pass

class Store:
 def __init__(self,path,clock=time.time):
  self.path=Path(path);self.clock=clock;self.limits={};self.lock=threading.Lock()
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.db() as c:
   c.executescript('''CREATE TABLE IF NOT EXISTS pairs(id TEXT PRIMARY KEY, challenge TEXT NOT NULL, owner TEXT NOT NULL, scope TEXT NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL, claim TEXT, code TEXT, label TEXT);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, secret TEXT UNIQUE NOT NULL, owner TEXT NOT NULL, scope TEXT NOT NULL, expires REAL NOT NULL, label TEXT NOT NULL, created REAL NOT NULL);''')
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path,timeout=3);c.row_factory=sqlite3.Row
  try:
   c.execute('BEGIN IMMEDIATE');yield c;c.commit()
  except Exception:c.rollback();raise
  finally:c.close()
 def limit(self,key,cap=20):
  now=self.clock()
  with self.lock:
   self.limits={k:v for k,v in self.limits.items() if v[0]>now-60}
   start,count=self.limits.get(key,(now,0))
   if count>=cap:raise Denied('Too many attempts. Wait one minute.')
   self.limits[key]=(start,count+1)
 def clean(self,c):
  c.execute('DELETE FROM pairs WHERE expires<=?',(self.clock(),));c.execute('DELETE FROM sessions WHERE expires<=?',(self.clock(),))
 def create(self,owner,scope):
  self.limit('create:'+owner,5);ident=secrets.token_urlsafe(18);secret=secrets.token_urlsafe(32)
  with self.db() as c:
   self.clean(c)
   if c.execute('SELECT count(*) FROM pairs').fetchone()[0]>=32:raise Denied('Pairing capacity reached')
   c.execute('INSERT INTO pairs VALUES(?,?,?,?,?,?,NULL,NULL,NULL)',(ident,digest(secret),owner,json.dumps(scope,sort_keys=True),self.clock()+300,'pending'))
  return {'id':ident,'challenge':secret,'expires_in':300}
 def pair(self,c,ident):
  p=c.execute('SELECT * FROM pairs WHERE id=?',(ident,)).fetchone()
  if p is None or p['expires']<=self.clock():raise Denied('Pairing expired or unavailable')
  return p
 def claim(self,ident,challenge,label):
  self.limit('claim',20);secret=secrets.token_urlsafe(32);code=str(secrets.randbelow(1000000)).zfill(6)
  with self.db() as c:
   p=self.pair(c,ident)
   if p['state']!='pending' or not hmac.compare_digest(p['challenge'],digest(challenge)):raise Denied('Pairing expired or unavailable')
   c.execute("UPDATE pairs SET state='claimed',claim=?,code=?,label=? WHERE id=?",(digest(secret),code,label,ident))
  return {'claim':secret,'code':code,'status':'waiting_for_pc_approval'}
 def owner_status(self,ident,owner):
  with self.db() as c:
   p=self.pair(c,ident)
   if p['owner']!=owner:raise Denied('Pairing unavailable')
   return {'id':ident,'status':p['state'],'code':p['code'],'label':p['label'],'expires':p['expires']}
 def approve(self,ident,owner,code):
  self.limit('approve:'+owner,10)
  with self.db() as c:
   p=self.pair(c,ident)
   if p['owner']!=owner or p['state']!='claimed' or not hmac.compare_digest(p['code'],code):raise Denied('Matching phone confirmation required')
   c.execute("UPDATE pairs SET state='approved' WHERE id=?",(ident,))
 def cancel(self,ident,owner):
  with self.db() as c:c.execute('DELETE FROM pairs WHERE id=? AND owner=?',(ident,owner))
 def redeem(self,ident,claim,owners):
  self.limit('redeem',60)
  with self.db() as c:
   p=self.pair(c,ident)
   if not p['claim'] or not hmac.compare_digest(p['claim'],digest(claim)) or p['owner'] not in owners:raise Denied('Pairing unavailable')
   if p['state']=='claimed':return None
   if p['state']!='approved':raise Denied('Pairing unavailable')
   if len(c.execute('SELECT id FROM sessions WHERE owner=?',(p['owner'],)).fetchall())>=20:raise Denied('Revoke an old device before pairing')
   secret=secrets.token_urlsafe(32);ident2=secrets.token_urlsafe(18)
   c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)',(ident2,digest(secret),p['owner'],p['scope'],self.clock()+TTL,p['label'],self.clock()))
   c.execute('DELETE FROM pairs WHERE id=?',(ident,))
  return secret
 def resolve(self,secret,owners):
  with self.db() as c:
   r=c.execute('SELECT * FROM sessions WHERE secret=?',(digest(secret),)).fetchone()
   if r is None or r['expires']<=self.clock() or r['owner'] not in owners:raise Denied('Sign in required')
   granted=json.loads(r['scope']);current=owners[r['owner']]
   granted['projects']=sorted(set(granted.get('projects',[]))&set(current.get('projects',[])))
   granted['write']=bool(granted.get('write') and current.get('write'))
   from system_summary import SCRIPTS,listed
   granted['system_summary_read']=[name for name in SCRIPTS if listed(name,granted) and listed(name,current)]
   granted['network_read']=granted.get('network_read') is True and current.get('network_read') is True
   granted['network_endpoints']=[]  # This policy release grants metadata only, never connectivity.
   return granted,dict(r)
 def devices(self,owner):
  with self.db() as c:
   self.clean(c);return [dict(r) for r in c.execute('SELECT id,label,created,expires FROM sessions WHERE owner=? ORDER BY created',(owner,))]
 def resolve_id(self,identifier,owners):
  # Server-only durable dispatch lookup. The ID is not a login credential.
  with self.db() as c:
   r=c.execute('SELECT * FROM sessions WHERE id=?',(identifier,)).fetchone()
   if r is None or r['expires']<=self.clock() or r['owner'] not in owners:raise Denied('Queued device grant revoked')
   saved=json.loads(r['scope']);current=owners[r['owner']]
   granted={k:v for k,v in saved.items() if current.get(k)==v}
   granted['projects']=sorted(set(saved.get('projects',[]))&set(current.get('projects',[])))
   granted['write']=bool(saved.get('write') and current.get('write'))
   granted['network_endpoints']=[]
   return granted
 def revoke(self,owner,ident):
  with self.db() as c:c.execute('DELETE FROM sessions WHERE owner=? AND id=?',(owner,ident))
 def logout(self,secret):
  with self.db() as c:c.execute('DELETE FROM sessions WHERE secret=?',(digest(secret),))

def register(app,credentials,path):
 from fastapi import Request,HTTPException
 from fastapi.responses import JSONResponse
 from pydantic import BaseModel,Field,ConfigDict
 from reportlab.graphics.barcode import qrencoder as qr
 store=Store(path)
 def owners():return {digest(k):v for k,v in credentials.items()}
 app.state.resolve_dispatch_device=lambda identifier:store.resolve_id(identifier,owners())
 def secure(request,mutating=False):
  if request.headers.get('host')!=urlsplit(ORIGIN).netloc:raise HTTPException(403,'Use the private HTTPS Logis address')
  if mutating and request.headers.get('origin')!=ORIGIN:raise HTTPException(403,'Same-origin HTTPS request required')
 def bearer(request):
  secure(request,True)
  auth=request.headers.get('authorization','')
  if not auth.startswith('Bearer '):raise HTTPException(401,'Sign in on the PC with the existing token')
  key=auth[7:];scope=next((v for k,v in credentials.items() if hmac.compare_digest(k,key)),None)
  if scope is None:raise HTTPException(401,'Sign in required')
  return digest(key),scope
 def call(fn,*args):
  try:return fn(*args)
  except Denied as e:raise HTTPException(409,str(e)) from None
  except sqlite3.Error:raise HTTPException(503,'Device access store unavailable') from None
 @app.middleware('http')
 async def device_csrf(request,call_next):
  if request.url.path.startswith('/api/') and request.cookies.get(COOKIE) and not request.headers.get('authorization','').startswith('Bearer '):
   try:
    secure(request,request.method not in ('GET','HEAD','OPTIONS'))
    if request.method not in ('GET','HEAD','OPTIONS'):
     expected=digest('csrf:'+request.cookies[COOKIE])
     if not hmac.compare_digest(request.headers.get('x-logis-csrf',''),expected):return JSONResponse({'detail':'CSRF validation failed'},403)
   except HTTPException as e:return JSONResponse({'detail':e.detail},e.status_code)
  response=await call_next(request)
  if request.url.path.startswith('/api/device'):response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
  return response
 def session_scope(request):
  secure(request)
  value=request.cookies.get(COOKIE)
  if not value:raise HTTPException(401,'Authentication required')
  granted,row=call(store.resolve,value,owners())
  return {**granted,'_dispatch_identity':{'kind':'device','id':row['id']}}
 class Claim(BaseModel):
  model_config=ConfigDict(extra='forbid')
  id:str=Field(max_length=64);challenge:str=Field(max_length=100);label:str=Field(min_length=1,max_length=60)
 class Redemption(BaseModel):
  model_config=ConfigDict(extra='forbid')
  id:str=Field(max_length=64);claim:str=Field(max_length=100)
 class Approval(BaseModel):
  model_config=ConfigDict(extra='forbid')
  id:str=Field(max_length=64);code:str=Field(pattern=r'^\d{6}$')
 class Identifier(BaseModel):
  model_config=ConfigDict(extra='forbid')
  id:str=Field(max_length=64)
 @app.post('/api/device/create')
 def create(request:Request):
  owner,scope=bearer(request);value=call(store.create,owner,scope)
  url=ORIGIN+'/preview#pair='+value['id']+'.'+value.pop('challenge')
  q=qr.QRCode(None,qr.QRErrorCorrectLevel.M);q.addData(qr.QR8bitByte(url));q.make();n=len(q.modules)
  cells=''.join(f'<rect x="{x+4}" y="{y+4}" width="1" height="1"/>' for y,row in enumerate(q.modules) for x,on in enumerate(row) if on)
  value['svg']=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n+8} {n+8}" shape-rendering="crispEdges"><rect width="{n+8}" height="{n+8}" fill="white"/><g fill="black">{cells}</g></svg>'
  # Same five-minute challenge already encoded in the QR, never the master token.
  # Authenticated native owner helper may open the local browser without decoding it.
  value['pair_url']=url
  return value
 @app.post('/api/device/status')
 def status(body:Identifier,request:Request):owner,_=bearer(request);return call(store.owner_status,body.id,owner)
 @app.post('/api/device/approve')
 def approve(body:Approval,request:Request):owner,_=bearer(request);call(store.approve,body.id,owner,body.code);return {'status':'approved'}
 @app.post('/api/device/cancel')
 def cancel(body:Identifier,request:Request):owner,_=bearer(request);store.cancel(body.id,owner);return {'status':'cancelled'}
 @app.post('/api/device/claim')
 def claim(body:Claim,request:Request):secure(request,True);return call(store.claim,body.id,body.challenge,body.label)
 @app.post('/api/device/redeem')
 def redeem(body:Redemption,request:Request):
  secure(request,True);secret=call(store.redeem,body.id,body.claim,owners())
  if secret is None:return {'status':'waiting_for_pc_approval'}
  response=JSONResponse({'status':'paired'});response.set_cookie(COOKIE,secret,max_age=TTL,secure=True,httponly=True,samesite='strict',path='/');return response
 @app.get('/api/device/session')
 def session(request:Request):
  secure(request);secret=request.cookies.get(COOKIE,'');_,r=call(store.resolve,secret,owners())
  return {'status':'paired','csrf':digest('csrf:'+secret),'expires':r['expires'],'label':r['label']}
 @app.post('/api/device/list')
 def devices(request:Request):owner,_=bearer(request);return {'devices':store.devices(owner)}
 @app.post('/api/device/revoke')
 def revoke(body:Identifier,request:Request):owner,_=bearer(request);store.revoke(owner,body.id);return {'status':'revoked'}
 @app.post('/api/device/logout')
 def logout(request:Request):
  secure(request,True);store.logout(request.cookies.get(COOKIE,''));response=JSONResponse({'status':'signed_out'});response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict');return response
 return session_scope
