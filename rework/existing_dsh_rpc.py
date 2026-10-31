"""Bounded loopback DSH RPC using an explicitly supplied existing cookie reader."""
import http.client,json,socket,threading,uuid

class ExistingDshRPC:
    METHODS={'session/create','session/prompt','session/projections','session/page','session/cancel','session/list'}
    def __init__(self,port,cookie_reader):
        if type(port) is not int or not 1024<=port<=65535 or not callable(cookie_reader):raise ValueError('Explicit existing loopback port and cookie reader required')
        self.port,self.cookie_reader=port,cookie_reader
    def __call__(self,method,args):
        if method not in self.METHODS or type(args) is not dict:raise ValueError('Unsupported local RPC operation')
        cookie=self.cookie_reader()
        if not isinstance(cookie,str) or not cookie or len(cookie)>8192 or '\r' in cookie or '\n' in cookie:raise ValueError('Existing bounded cookie required')
        body=json.dumps({'type':'client-request','rpcId':uuid.uuid4().hex,'method':method,'payload':{'args':args}}).encode()
        if len(body)>262144:raise ValueError('Local RPC request exceeds bound')
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        active=[None];response=None
        def abort():
            sock=active[0] or connection.sock
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        timer=threading.Timer(15,abort);timer.daemon=True;timer.start()
        try:
            connection.request('POST','/api/'+method,body=body,headers={'Content-Type':'application/json','Cookie':cookie})
            active[0]=connection.sock
            response=connection.getresponse()
            if response.status!=200:raise RuntimeError('Existing local RPC authorization or request failed')
            raw=response.read(1048577)
            if len(raw)>1048576:raise ValueError('Local RPC response exceeds bound')
            value=json.loads(raw)
            if type(value) is not dict:raise ValueError('Local RPC response must be an object')
            return value
        finally:
            timer.cancel()
            if response is not None:response.close()
            connection.close()
