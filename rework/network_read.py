"""Fixed read-only adapters; no firewall/DNS/route/VPN mutations or scan loops."""
import subprocess,os,json,socket,time
from pathlib import Path
from network_contract import connectivity_request
from optional_policy import network_current
from bounded_native import run_bounded

SCRIPTS={
 'network_interfaces':"Get-NetIPConfiguration | Select-Object InterfaceAlias,InterfaceIndex,@{n='IPv4';e={@($_.IPv4Address.IPAddress)}},@{n='IPv6';e={@($_.IPv6Address.IPAddress)}}",
 'network_routes':"$total=0; $defaultTotal=0; $families=@{IPv4=0;IPv6=0;Other=0}; $states=@{Alive=0;Dead=0;Probe=0;Other=0}; $sample=@(); Get-NetRoute | ForEach-Object { $total++; $af=[string]$_.AddressFamily; if (-not $families.ContainsKey($af)) {$af='Other'}; $families[$af]++; $state=[string]$_.State; if (-not $states.ContainsKey($state)) {$state='Other'}; $states[$state]++; if ($_.DestinationPrefix -in @('0.0.0.0/0','::/0')) { $defaultTotal++; if ($sample.Count -lt 4) { $sample+=@{family=$af;destination=[string]$_.DestinationPrefix;interface_index=[long]$_.InterfaceIndex;next_hop=[string]$_.NextHop;metric=[long]$_.RouteMetric;state=$state} } } }; @{total_observed=$total;family_counts=$families;state_counts=$states;default_total=$defaultTotal;sample_count=$sample.Count;omitted_default_count=($defaultTotal-$sample.Count);omitted_route_detail_count=($total-$sample.Count);defaults=@($sample);selection='first_four_defaults_provider_order'}",
 'network_dns':"Get-DnsClientServerAddress | Select-Object InterfaceIndex,AddressFamily,ServerAddresses",
}
def route_summary(value):
    import ipaddress
    if type(value) is not list or len(value)!=1 or type(value[0]) is not dict:raise ValueError('Invalid bounded route summary')
    r=value[0]
    keys={'total_observed','family_counts','state_counts','default_total','sample_count','omitted_default_count','omitted_route_detail_count','defaults','selection'}
    if set(r)!=keys or r['selection']!='first_four_defaults_provider_order':raise ValueError('Invalid route fields')
    def count(x):return type(x) is int and 0<=x<=2147483647
    for k in ['total_observed','default_total','sample_count','omitted_default_count','omitted_route_detail_count']:
        if not count(r[k]):raise ValueError('Invalid route counts')
    for field,allowed in [('family_counts',{'IPv4','IPv6','Other'}),('state_counts',{'Alive','Dead','Probe','Other'})]:
        if type(r[field]) is not dict or set(r[field])!=allowed or any(not count(x) for x in r[field].values()) or sum(r[field].values())!=r['total_observed']:raise ValueError('Inconsistent route buckets')
    if not 0<=r['sample_count']<=4 or not r['sample_count']==min(4,r['default_total']) or r['default_total']>r['total_observed'] or r['omitted_default_count']!=r['default_total']-r['sample_count'] or r['omitted_route_detail_count']!=r['total_observed']-r['sample_count']:raise ValueError('Inconsistent route coverage')
    if type(r['defaults']) is not list or len(r['defaults'])!=r['sample_count']:raise ValueError('Invalid default sample')
    family_sample={'IPv4':0,'IPv6':0}
    state_sample={key:0 for key in r['state_counts']}
    for row in r['defaults']:
        if type(row) is not dict or set(row)!={'family','destination','interface_index','next_hop','metric','state'}:raise ValueError('Invalid default route fields')
        if row['family'] not in family_sample or row['destination']!=('0.0.0.0/0' if row['family']=='IPv4' else '::/0') or row['state'] not in r['state_counts']:raise ValueError('Invalid default route classification')
        if not count(row['interface_index']) or not count(row['metric']):raise ValueError('Invalid default route metric/index')
        hop=row['next_hop']
        if type(hop) is not str or len(hop)>64:raise ValueError('Invalid next hop')
        if '%' in hop and (hop.count('%')!=1 or not hop.split('%')[1].isdigit()):raise ValueError('Invalid next hop zone')
        address=ipaddress.ip_address(hop)
        if address.version!=(4 if row['family']=='IPv4' else 6):raise ValueError('Next hop family mismatch')
        family_sample[row['family']]+=1
        state_sample[row['state']]+=1
    if any(family_sample[k]>r['family_counts'][k] for k in family_sample):raise ValueError('Sample exceeds family coverage')
    if any(state_sample[k]>r['state_counts'][k] for k in state_sample):raise ValueError('Sample exceeds state coverage')
    return {**r,'coverage':'Counts cover routes returned by this one completed native enumeration. Details include only first four default routes in provider order, not best routes or the full table. Other state/family buckets preserve unknown categories. No external reachability proof.'}

def metadata(name,permissions,runner=run_bounded):
    if not network_current(permissions):raise PermissionError('Current network metadata scope not granted; no query executed')
    if name not in SCRIPTS:raise ValueError('Unknown read-only network tool')
    if os.name!='nt':raise ValueError('Windows adapter unavailable')
    exe=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    command="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; @( "+SCRIPTS[name]+" ) | ConvertTo-Json -Depth 5 -Compress"
    if name=='network_routes':command="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $summary=@( "+SCRIPTS[name]+" ); ConvertTo-Json -InputObject $summary -Depth 5 -Compress"
    if not network_current(permissions):raise PermissionError('Network metadata scope withdrawn before query')
    result=runner([exe,'-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Network metadata unavailable under current account; no elevated retry')
    if len(result.stdout)>4096:raise ValueError('Network metadata exceeds bounded result; no partial claim')
    value=json.loads(result.stdout.decode('utf-8-sig')) if result.stdout.strip() else []
    if name=='network_routes':value=route_summary(value)
    return {'tool':name,'records':value,'effects':'none','scope':'local metadata; not proof of external reachability','limit':'4096 native output bytes; route default sample max4' if name=='network_routes' else '4096 output bytes'}

def connectivity(target,port,permissions,connector=socket.create_connection):
    if not network_current(permissions):raise PermissionError('Current network scope not granted')
    endpoints=permissions.get('network_endpoints',[])
    if not isinstance(endpoints,list) or any(not isinstance(x,dict) or set(x)!={'target','port'} or not isinstance(x['target'],str) or type(x['port']) is not int for x in endpoints):
        raise PermissionError('Exact IP/port endpoint grants required')
    if not any(x['target']==target and x['port']==port for x in endpoints):raise PermissionError('Exact IP/port pair not approved')
    request=connectivity_request(target,port,[x['target'] for x in endpoints if x['port']==port])
    start=time.monotonic()
    # Hostname resolution can exceed socket timeout on some OS resolvers. Until
    # an independently tested bounded resolver exists, connect only explicit IPs.
    import ipaddress
    try:ipaddress.ip_address(target)
    except ValueError:raise ValueError('Bounded hostname resolution not implemented; use an explicitly approved IP target')
    try:
        with connector((target,port),timeout=3):pass
        state='connected'
    except OSError:state='unreachable_or_rejected'
    return {**request,'status':state,'seconds':round(time.monotonic()-start,3),'effects':'one TCP handshake; no application payload sent'}
