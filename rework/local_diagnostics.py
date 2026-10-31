"""Fixed read-only Windows query, no model-provided commands or elevation."""
import json,os,subprocess,datetime
from pathlib import Path

SCRIPT=r'''
$ErrorActionPreference='Stop'
$names=@{}; Get-Process | ForEach-Object { $names[[string]$_.Id]=$_.ProcessName }
$tcp=@(Get-NetTCPConnection -State Listen | Sort-Object LocalPort,LocalAddress)
$udp=@(Get-NetUDPEndpoint | Sort-Object LocalPort,LocalAddress)
$rows=@($tcp | Select-Object -First 192 | ForEach-Object { [pscustomobject]@{protocol='TCP';address=$_.LocalAddress;port=$_.LocalPort;pid=$_.OwningProcess;process=$names[[string]$_.OwningProcess]} })
$rows+=@($udp | Select-Object -First 64 | ForEach-Object { [pscustomobject]@{protocol='UDP';address=$_.LocalAddress;port=$_.LocalPort;pid=$_.OwningProcess;process=$names[[string]$_.OwningProcess]} })
[pscustomobject]@{rows=$rows;tcp_count=$tcp.Count;udp_count=$udp.Count;truncated=($tcp.Count -gt 192 -or $udp.Count -gt 64)} | ConvertTo-Json -Depth 4 -Compress
'''
def listeners(permissions,runner=subprocess.run):
    if permissions.get('owner') is not True:raise PermissionError('Local diagnostics require the existing owner scope; project credentials do not grant host access')
    if os.name!='nt':raise ValueError('Windows listener adapter unavailable on this host')
    exe=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=runner([str(exe),'-NoProfile','-NonInteractive','-Command',SCRIPT],capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Listener metadata unavailable under this account; no elevation attempted')
    if len(result.stdout)>80000:raise ValueError('Listener metadata exceeded bound')
    value=json.loads(result.stdout.decode('utf-8-sig'))
    rows=value.get('rows',[])
    if not isinstance(rows,list) or len(rows)>256:raise ValueError('Invalid listener metadata')
    for row in rows:
        if row.get('protocol') not in ('TCP','UDP') or not isinstance(row.get('port'),int) or not 0<=row['port']<=65535:raise ValueError('Invalid listener record')
    return {'status':'observed','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':'Windows Get-NetTCPConnection/Get-NetUDPEndpoint and process name snapshot','data':value,
      'answer':'Local listener/endpoint snapshot (not externally reachable-port testing). Process names are best-effort; missing names mean unknown. Port 3000 is reserved for Antigravity/Hermes; no changes were made.\n'+json.dumps(value,ensure_ascii=False),
      'effects':'none; no firewall, process, port or network changes'}
