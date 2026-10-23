"""MCP stdio bridge to the running Logis shared registry."""
import json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import server as app
def main():
    for line in sys.stdin:
        request={}
        try:
            request=json.loads(line);method=request.get('method');rid=request.get('id')
            if rid is None:continue
            if method=='initialize':result={'protocolVersion':request.get('params',{}).get('protocolVersion','2025-03-26'),'capabilities':{'tools':{}},'serverInfo':{'name':'Logis shared tools','version':'1.0.0'}}
            elif method=='ping':result={}
            elif method=='tools/list':
                tools=[{'name':'atlas_projects','description':'List available Logis project IDs','inputSchema':{'type':'object','properties':{}}}]
                for t in app.TOOLS+app.POWER_TOOLS+app.CLI_TOOLS+app.KNOWLEDGE_TOOLS+app.DOCUMENT_TOOLS+app.REA_TOOLS:
                    fn=t['function'];schema=json.loads(json.dumps(fn['parameters']));schema['properties']['project_id']={'type':'string'};schema['required']=schema.get('required',[])+['project_id']
                    tools.append({'name':fn['name'],'description':fn['description'],'inputSchema':schema})
                result={'tools':tools}
            elif method=='tools/call':
                data=request['params'];args=dict(data.get('arguments',{}))
                if data['name']=='atlas_projects':
                    with urllib.request.urlopen('http://127.0.0.1:8090/api/projects') as response:value=json.load(response)
                else:
                    auth=json.loads((ROOT/'runtime/mcp-auth.json').read_text());payload={'id':args.pop('project_id'),'name':data['name'],'arguments':args}
                    req=urllib.request.Request('http://127.0.0.1:8090/api/mcp',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Workspace-Token':auth['token']})
                    with urllib.request.urlopen(req,timeout=180) as response:value=json.load(response)
                result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':bool(isinstance(value,dict) and value.get('error'))}
            else:raise ValueError('Unsupported MCP method')
            print(json.dumps({'jsonrpc':'2.0','id':rid,'result':result}),flush=True)
        except Exception as e:
            message=str(e)
            if hasattr(e,'read'):
                try:message=json.loads(e.read())['error']
                except Exception:pass
            print(json.dumps({'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32603,'message':message}}),flush=True)
if __name__=='__main__':main()
