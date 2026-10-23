"""Reviewed Windows host commands. A working directory is not a sandbox."""
import json,os,re,subprocess,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUNNING={};GUARD=threading.Lock()
def configure(atomic,now):
    global ATOMIC,NOW
    ATOMIC,NOW=atomic,now
def cli_command(folder,cmd,root='',path='.',timeout_seconds=60):
    import knowledge
    if not isinstance(cmd,str) or not 1<=len(cmd)<=4000:raise ValueError('Use a command up to 4000 characters')
    timeout=max(5,min(int(timeout_seconds),300))
    if root:
        entry,cwd=knowledge.target(root,path)
        if not entry['writable']:raise ValueError('Host CLI requires a writable connected folder')
    else:
        cwd=knowledge.SAFE(folder/'files',path)
    if not cwd.is_dir():raise ValueError('Working folder must exist')
    request={'id':uuid.uuid4().hex,'kind':'host_cli','status':'pending','command':cmd,'cwd':str(cwd.resolve()),'root':root,'path':path,'timeout_seconds':timeout,'created':time.time(),'notice':'Runs on your PC with your Windows user permissions. The working folder is not a security sandbox. Review the exact command before approving.'}
    ATOMIC(folder/'approvals'/f"{request['id']}.json",request)
    return {'approval_required':True,'request_id':request['id'],'command':cmd,'cwd':request['cwd'],'message':'Review this Windows command in Inbox. After it completes, Continue can inspect cli_result.'}
def cli_result(folder,request_id):
    if not re.fullmatch(r'[a-f0-9]{32}',request_id):raise ValueError('Invalid command request ID')
    record=json.loads((folder/'approvals'/f'{request_id}.json').read_text(encoding='utf-8'))
    if record['kind']!='host_cli':raise ValueError('Not a CLI request')
    return record
def approve(folder,request):
    import knowledge
    if request.get('root'):
        entry,cwd=knowledge.target(request['root'],request['path'])
        if not entry['writable'] or str(cwd.resolve())!=request['cwd']:raise ValueError('Folder access changed. Prepare a new command request')
    else:
        cwd=knowledge.SAFE(folder/'files',request['path'])
        if str(cwd.resolve())!=request['cwd']:raise ValueError('Working folder changed')
    with GUARD:
        if RUNNING:raise ValueError('Another Windows CLI command is running')
        request['status']='running';request['started']=NOW();RUNNING[request['id']]={'project':folder.name,'command':request['command'],'phase':'Windows CLI'}
        ATOMIC(folder/'approvals'/f"{request['id']}.json",request)
    threading.Thread(target=execute,args=(folder,request),daemon=True).start();return request
def execute(folder,request):
    pwsh=Path('C:/Users/LOGIS_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe')
    allowed=('SystemRoot','WINDIR','ComSpec','PATH','PATHEXT','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA','OS','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE')
    env={k:v for k,v in os.environ.items() if k.upper() in {x.upper() for x in allowed}}
    try:
        result=subprocess.run([str(pwsh),'-NoLogo','-NoProfile','-NonInteractive','-Command',request['command']],cwd=request['cwd'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=request['timeout_seconds'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        request.update(status='completed' if result.returncode==0 else 'failed',exit_code=result.returncode,stdout=result.stdout[-24000:],stderr=result.stderr[-12000:])
    except subprocess.TimeoutExpired as e:request.update(status='failed',error='Command exceeded its approved time limit',stdout=str(e.stdout or '')[-12000:])
    except Exception as e:request.update(status='failed',error=str(e))
    finally:
        request['finished']=NOW()
        try:
            ATOMIC(folder/'approvals'/f"{request['id']}.json",request)
            with (folder/'actions.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps({'time':NOW(),'tool':'Windows CLI','result':request},ensure_ascii=False)+'\n')
        finally:
            with GUARD:RUNNING.pop(request['id'],None)
def schemas(tool,STR):
    return [tool('cli_command','Prepare a Windows PowerShell command for human approval in Inbox. Executes on the host PC, not in Docker; working folder is not a sandbox. Never claim it ran until cli_result confirms completion. Root defaults to project files; connected roots require write access.',{'cmd':STR,'root':STR,'path':STR,'timeout_seconds':{'type':'integer'}},['cmd']),tool('cli_result','Read the status/output of a reviewed Windows CLI command. Use after the user approves and it completes.',{'request_id':STR},['request_id'])]
FUNCTIONS={f.__name__:f for f in (cli_command,cli_result)}
