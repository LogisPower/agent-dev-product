"""Fixed native metadata summaries. No names, commands, event messages or grants."""
import os,json,subprocess,datetime,time,math
from pathlib import Path
SCRIPTS={
 'system_summary':"$x=Get-CimInstance -ClassName Win32_OperatingSystem -Property TotalVisibleMemorySize,FreePhysicalMemory; @{total_memory_kib=[long]$x.TotalVisibleMemorySize;available_memory_kib=[long]$x.FreePhysicalMemory}",
 'service_summary':"$x=@(Get-Service); @{sampled=$x.Count;running=@($x | Where-Object Status -eq Running).Count;stopped=@($x | Where-Object Status -eq Stopped).Count;other=@($x | Where-Object { $_.Status -notin @('Running','Stopped') }).Count}",
 'startup_summary':"$x=@(Get-CimInstance -Query 'SELECT Name FROM Win32_StartupCommand'); @{visible_entry_count=$x.Count}",
 'event_summary':"$x=@(Get-WinEvent -FilterHashtable @{LogName='System';StartTime=(Get-Date).AddHours(-24);Level=1,2,3} -MaxEvents 32); @{sampled=$x.Count;critical=@($x | Where-Object Level -eq 1).Count;error=@($x | Where-Object Level -eq 2).Count;warning=@($x | Where-Object Level -eq 3).Count}"
}
FIELDS={'system_summary':{'total_memory_kib','available_memory_kib'},'service_summary':{'sampled','running','stopped','other'},'startup_summary':{'visible_entry_count'},'event_summary':{'sampled','critical','error','warning'}}
COVERAGE={'system_summary':'One OS memory snapshot in KiB, not commit/paging/CPU diagnosis.','service_summary':'Counts of services visible to the current account, no names, paths, accounts or configuration.','startup_summary':'Count of visible Win32_StartupCommand entries only; excludes other startup mechanisms, scheduled tasks and service startup.','event_summary':'Up to32 latest critical/error/warning System events in last24h. No messages, providers, IDs or personal fields. Not a complete event inventory or root-cause finding.'}
def listed(name,permissions):
 value=permissions.get('system_summary_read')
 return name in SCRIPTS and type(value) is list and len(value)==len(set(x for x in value if type(x) is str)) and all(type(x) is str and x in SCRIPTS for x in value) and name in value

class SummaryScope(dict):pass

def bind_scope(base,current):
 import copy
 value=SummaryScope(copy.deepcopy(dict(base)))
 if hasattr(base,'setup_health_allowed'):value.setup_health_allowed=base.setup_health_allowed
 value.current_summary_scope=current
 return value

def authorized(name,permissions):
 if not listed(name,permissions):return False
 callback=getattr(permissions,'current_summary_scope',None)
 if callback is None:return True  # Discovery only; native execution requires callback.
 try:
  fresh=callback()
  return listed(name,fresh) and bool(permissions.get('projects')) and set(permissions['projects']).issubset(fresh.get('projects',[]))
 except Exception:return False

from bounded_native import run_bounded

def collect(name,permissions,runner=run_bounded):
 def result(status,reason,data=None):return {'tool':name,'status':status,'reason':reason,'records':data,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':'fixed Windows PowerShell native metadata query','coverage':COVERAGE.get(name,'Unsupported tool'),'effects':'none','bounds':{'deadline_seconds':8,'stdout_bytes':4096,'stderr_capture_bytes':1024,'cleanup_grace_seconds_max':3,'event_sample_max':32},'automatic_elevation':False}
 if name not in SCRIPTS:return result('unavailable','unknown_tool')
 if not callable(getattr(permissions,'current_summary_scope',None)) or not authorized(name,permissions):return result('denied','exact_system_summary_scope_required')
 if os.name!='nt':return result('unavailable','windows_required')
 # Error identifiers are classified inside PowerShell. Raw errors never enter
 # receipts (they can include local paths, usernames or event payloads).
 cmd="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; try { $d= & { "+SCRIPTS[name]+" }; @{status='ok';data=$d} | ConvertTo-Json -Compress } catch { $s='unavailable'; if ($_.CategoryInfo.Category -eq 'PermissionDenied' -or $_.Exception -is [UnauthorizedAccessException]) {$s='denied'}; if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {$s='empty'}; @{status=$s} | ConvertTo-Json -Compress }"
 try:
  if not authorized(name,permissions):return result('denied','scope_withdrawn_before_native_start')
  out=runner([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),'-NoProfile','-NonInteractive','-Command',cmd],capture_output=True,timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if out.returncode:return result('unavailable','native_query_failed')
  if len(out.stdout)>4096:return result('unavailable','output_bound_exceeded')
  value=json.loads(out.stdout.decode('utf-8-sig'))
  if value=={'status':'denied'}:return result('denied','os_access_denied')
  if value=={'status':'empty'} and name=='event_summary':return result('read','no_matching_events_in_window',{'sampled':0,'critical':0,'error':0,'warning':0})
  if value=={'status':'unavailable'}:return result('unavailable','native_query_unavailable')
  if not isinstance(value,dict) or set(value)!={'status','data'} or value['status']!='ok':raise ValueError()
  data=value['data']
  if not isinstance(data,dict) or set(data)!=FIELDS[name] or any(type(v) is not int or v<0 or v>2**53 for v in data.values()):raise ValueError()
  if name=='system_summary' and data['available_memory_kib']>data['total_memory_kib']:raise ValueError()
  if name=='service_summary' and data['sampled']!=data['running']+data['stopped']+data['other']:raise ValueError()
  if name=='event_summary' and (data['sampled']>32 or data['sampled']!=data['critical']+data['error']+data['warning']):raise ValueError()
  return result('read','bounded_snapshot',data)
 except subprocess.TimeoutExpired:return result('unavailable','deadline_exceeded_no_retry')
 except (OSError,ValueError,TypeError,KeyError,UnicodeError):return result('unavailable','invalid_or_unavailable_native_result')
