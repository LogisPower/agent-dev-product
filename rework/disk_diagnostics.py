"""Bounded read-only disk evidence and a non-executable elevated trace proposal.

No cleanup, antivirus verdict, arbitrary commands, file scan or permanent monitor.
Normal aggregate counters cannot attribute writes to individual files.
"""
import os,json,subprocess,time,hashlib,datetime,sys
from pathlib import Path

CAPACITY="[IO.DriveInfo]::new('C:\\') | Select-Object Name,DriveFormat,TotalSize,AvailableFreeSpace,IsReady"
ACTIVITY=r"""
$paths=@('\LogicalDisk(C:)\% Idle Time','\LogicalDisk(C:)\Avg. Disk sec/Read','\LogicalDisk(C:)\Avg. Disk sec/Write','\LogicalDisk(C:)\Current Disk Queue Length','\LogicalDisk(C:)\Disk Read Bytes/sec','\LogicalDisk(C:)\Disk Write Bytes/sec','\Memory\Available MBytes','\Memory\Pages Input/sec','\Memory\Pages Output/sec')
# Resolve module/provider and discard exactly one predetermined priming sample.
# Keep the same counter session for five measured intervals. Never discard a
# measured sample according to its value or retry until favorable.
Import-Module Microsoft.PowerShell.Diagnostics -ErrorAction Stop
$index=0
$measured=@(Get-Counter -Counter $paths -SampleInterval 1 -MaxSamples 6 | ForEach-Object {
 if ($index -gt 0) {
  @{timestamp=$_.Timestamp.ToUniversalTime().ToString('o');counters=@($_.CounterSamples | Select-Object Path,CookedValue,Status)}
 }
 $index++
})
$measured

"""
PROCESS_IO=r"""
Get-Counter -Counter '\Process(*)\ID Process','\Process(*)\IO Read Bytes/sec','\Process(*)\IO Write Bytes/sec' -SampleInterval 1 -MaxSamples 2 | Select-Object -Last 1 | ForEach-Object {
 $_.CounterSamples | Where-Object {$_.InstanceName -notin @('_total','idle')} | Group-Object InstanceName | ForEach-Object {
  $pidCounter=$_.Group | Where-Object {$_.Path -like '*\id process'}
  $reads=$_.Group | Where-Object {$_.Path -like '*\io read bytes/sec'}
  $writes=$_.Group | Where-Object {$_.Path -like '*\io write bytes/sec'}
  @{name=$_.Name;pid=$pidCounter.CookedValue;read_bytes_per_second=$reads.CookedValue;write_bytes_per_second=$writes.CookedValue;counter_status=@($_.Group.Status)}
 } | Sort-Object {[double]$_.read_bytes_per_second+[double]$_.write_bytes_per_second} -Descending | Select-Object -First 10
}
"""
SCRIPTS={'disk_capacity':CAPACITY,'disk_activity':ACTIVITY,'disk_process_io':PROCESS_IO}
def require_scope(permissions):
    if permissions.get('disk_read') is not True:raise PermissionError('Read-only disk metadata scope is not enabled; no query executed')
def collect(name,permissions,runner=subprocess.run):
    from setup_scope import request_allowed
    if not (name=='disk_activity' and request_allowed(permissions)):require_scope(permissions)
    if name not in SCRIPTS or os.name!='nt':raise ValueError('Supported Windows diagnostic required')
    command="$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; @( "+SCRIPTS[name]+" ) | ConvertTo-Json -Depth 5 -Compress"
    begin=time.monotonic()
    native=name=='disk_activity'
    argv=([sys.executable,'-I','-B',str(Path(__file__).with_name('native_activity.py'))] if native else
          [str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),'-NoProfile','-NonInteractive','-Command',command])
    try:
        result=runner(argv,capture_output=True,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired:
        if not native:raise
        return {'tool':name,'status':'unavailable','records':[],'failure':{'code':'collector_deadline','phase':'startup_or_native_call','deadline_seconds':12},'seconds':round(time.monotonic()-begin,3),'effects':'none','interpretation':'No usable telemetry. Timeout is not evidence of system pressure. No retry or elevated fallback.'}
    if result.returncode:raise ValueError('Disk counters unavailable under normal account or localized counter names; no elevation or alternate scan attempted')
    if len(result.stdout)>24000:raise ValueError('Diagnostic output bound exceeded; no partial success claimed')
    decoded=json.loads(result.stdout.decode('utf-8-sig'))
    if native:
        if not isinstance(decoded,dict) or decoded.get('status') not in ('ok','unavailable'):raise ValueError('Invalid native collector envelope')
        if decoded['status']=='unavailable':
            return {'tool':name,'status':'unavailable','records':[],'failure':decoded.get('failure'),'timings':decoded.get('timings'),'effects':'none','interpretation':'Unavailable telemetry, not proof of disk pressure; no retry.'}
        records=decoded.get('records')
        if decoded.get('measurement')!={'version':2,'warmup_samples_discarded':1,'measured_samples':5,'interval_seconds':1}:raise ValueError('Native measurement contract invalid')
    else:records=decoded
    if not isinstance(records,list) or not records:raise ValueError('No usable diagnostic samples returned')
    maximum={'disk_capacity':1,'disk_activity':5,'disk_process_io':10}[name]
    if len(records)>maximum:raise ValueError('Diagnostic record count exceeds contract')
    if name=='disk_activity' and any(not isinstance(r,dict) or not r.get('counters') or any(c.get('Status')!=0 for c in r['counters']) for r in records):raise ValueError('Invalid disk counter status; values are not reliable evidence')
    if name=='disk_process_io' and any(not isinstance(r,dict) or not r.get('counter_status') or any(x!=0 for x in r['counter_status']) for r in records):raise ValueError('Invalid process counter status; no attribution claimed')
    return {'tool':name,'records':records,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'seconds':round(time.monotonic()-begin,3),'timings':decoded.get('timings') if native else None,'collector':decoded.get('source') if native else 'PowerShell',
        'measurement':({'version':2,'warmup_samples_discarded':1,'measured_samples':5,'interval_seconds':1} if name=='disk_activity' else None),
        'effects':'none; no file-content reads or persistent monitoring','bounds':{'deadline_seconds':12,'output_bytes':24000,'samples_max':maximum},
        'scope':'C: capacity/activity or process-wide I/O counters. Process I/O includes other drives, devices and network; not C:-file attribution.',
        'interpretation':'Counter status must be valid before using values. Short samples can miss spikes. Low free space, paging and latency are distinct. This cannot establish malware, a failing drive, or which file caused a stall.'}
def trace_plan(project,permissions):
    require_scope(permissions)
    from workspace_facade import APPROVED_ROOT
    folder=APPROVED_ROOT/hashlib.sha256(project.encode()).hexdigest()/'.logis'/'diagnostics'
    contract={'schema_version':1,'operation':'proposed_file_level_disk_trace','project':project,'duration_seconds':15,'memory_buffer_mib_max':16,'output_bytes_max':67108864,
        'output_directory':str(folder),'requires_elevation':True,'approval':'New per-action owner approval and Windows elevation required; neither supplied by this proposal.',
        'privacy':'May record file paths/names, process identifiers and I/O timing across the machine; not file contents. Paths may reveal sensitive names.',
        'ownership':'Must use a unique trace-session ID. Stop only that session at deadline or failure; never stop another session.',
        'recovery':'Before any future launch, persist session identity and budget. A watchdog must stop the owned session and mark interrupted capture; no automatic restart.',
        'executor':'not implemented or enabled','effects':'none; no trace started, output directory not created','automatic_cleanup':False}
    return {**contract,'approval_hash':hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()}
