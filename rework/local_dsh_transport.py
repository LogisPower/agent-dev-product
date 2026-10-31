"""Existing DSH RPC bridge. Caller supplies authentication and the approved cwd.

No token discovery, login, model selection, permission changes or server startup.
RPC callback must apply a network timeout. Each durable job owns one fresh session.
"""
import json
import re
from pathlib import PurePosixPath


class DshTransport:
    def __init__(self, rpc, cwd, project):
        if not callable(rpc) or not isinstance(project,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',project) or not isinstance(cwd,str) or not cwd.startswith('/workspace/') or str(PurePosixPath(cwd))!=cwd or '..' in PurePosixPath(cwd).parts:
            raise ValueError('Existing authenticated RPC and exact approved container cwd required')
        self.rpc,self.cwd,self.project=rpc,cwd,project

    def session(self, request):
        if not isinstance(request,str) or not re.fullmatch('[a-f0-9]{32}',request):raise ValueError('Durable job ID required')
        return 'logis-work-'+request

    def call(self, method, args):
        response=self.rpc(method,args)
        if not isinstance(response,dict) or response.get('result',{}).get('ok') is not True:
            raise RuntimeError('Local RPC did not confirm operation')
        return response['result']['value']

    def submit(self, request, packet):
        session=self.session(request)
        if packet.get('request_id')!=request or packet.get('project')!=self.project:raise ValueError('Request identity or project mismatch')
        created=self.call('session/create',{'request':{'cwd':self.cwd,'sessionId':session}})
        if not isinstance(created,dict) or created.get('sessionId')!=session:raise ValueError('Session identity mismatch')
        prompt='Work only in '+self.cwd+'. Read only the named targets, apply each unique exact old/new replacement, then read back. Use at most 12 tool calls; no whole-file rewrites or exploration. Hash checks are performed by the caller. Stop on ambiguous anchors. '+json.dumps(packet,ensure_ascii=False)
        receipt=self.call('session/prompt',{'request':{'sessionId':session,'requestId':request,'mode':'queue','content':[{'type':'text','text':prompt}]}})
        return {'request_id':request,'accepted':isinstance(receipt,dict) and receipt.get('accepted') is True}

    def poll(self, request):
        session=self.session(request)
        projection=self.call('session/projections',{'request':{'sessionId':session}})
        page=self.call('session/page',{'request':{'address':{'kind':'session','sessionId':session},'throughSeq':projection['asOfSeq'],'maxMessages':8}})
        import hashlib
        status='running';calls=[]
        for record in page['records']:
            event=record['event']
            if event['type'] in ('turn/start','tool/call'):status='running'
            if event['type']=='tool/call':
                data=event.get('data',{})
                signature=hashlib.sha256(json.dumps({'name':data.get('name'),'arguments':data.get('arguments')},sort_keys=True).encode()).hexdigest()
                calls.append({'seq':event.get('seq'),'signature':signature})
            if event['type']=='turn/error':status='failed'
            if event['type']=='turn/end':
                reason=event['data'].get('reason',{}).get('kind')
                status='completed' if reason=='completed' else 'canceled' if reason=='canceled' else 'failed'
        stats=projection.get('values',{}).get('sessionStats') or {}
        return {'request_id':request,'status':status,'progress_seq':projection['asOfSeq'],
                'steps':stats.get('steps'),'tool_calls':calls}

    def cancel(self, request):
        self.call('session/cancel',{'request':{'sessionId':self.session(request)}})
