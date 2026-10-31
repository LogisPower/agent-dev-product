"""Staged network contracts. No command execution or persistent grants."""
import hashlib,json,ipaddress

READ_TOOLS={
    'network.interfaces':{'inputs':{},'scope':'local interface metadata'},
    'network.listeners':{'inputs':{},'scope':'local listeners; process ownership only where permitted'},
    'network.routes':{'inputs':{},'scope':'local route metadata'},
    'network.dns_config':{'inputs':{},'scope':'configured resolver metadata; no secrets'},
    'network.connectivity':{'inputs':{'target':'explicit approved hostname or IP','port':'integer1..65535'},'scope':'one approved target, no sweep'},
}
MUTATIONS={'dns.set','route.add','route.remove','firewall.change','tailscale.change'}

def connectivity_request(target,port,approved_targets):
    # Exact explicit targets; not a domain suffix, CIDR expansion or private-net grant.
    if not isinstance(approved_targets,(list,tuple,set,frozenset)) or any(not isinstance(t,str) or not t for t in approved_targets):
        raise PermissionError('Approved targets must be an explicit collection of exact strings')
    if not isinstance(target,str) or target not in approved_targets:
        raise PermissionError('Exact diagnostic target is not approved')
    if not target or len(target)>253 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:' for c in target):
        raise ValueError('Invalid target; URLs, credentials, paths and shell syntax forbidden')
    if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
        raise ValueError('Invalid port')
    return {'tool':'network.connectivity','target':target,'port':port,'attempts':1,'deadline_seconds':3,'interpretation':'Connection result only; not proof of general external reachability'}

def plan_change(kind,target,before,after,*,capture_id,captured_at,now,verification,rollback):
    """Pure proposal; cannot execute and cannot confer authorization."""
    if kind not in MUTATIONS:raise ValueError('Unknown change type')
    if not all(isinstance(x,str) and x.strip() for x in (target,capture_id,verification,rollback)):
        raise ValueError('Exact target, capture, verification and rollback required')
    if not isinstance(before,dict) or not isinstance(after,dict) or before==after:
        raise ValueError('Distinct structured before/after states required')
    if not isinstance(captured_at,(int,float)) or not 0<=now-captured_at<=60:
        raise ValueError('Fresh state capture required')
    body={'kind':kind,'target':target,'before':before,'after':after,'capture_id':capture_id,'captured_at':captured_at,'verification':verification,'rollback':rollback}
    raw=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(raw)>12000:raise ValueError('Proposal exceeds review bound')
    # Freeze the approval material as canonical bytes represented by a string;
    # caller-owned nested dictionaries cannot mutate it after hashing.
    return {'canonical_proposal_json':raw,'proposal_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'status':'proposed_not_executed','execution_available':False,
        'requires':'Exact action-time approval, adapter-specific validation and current-state match before any future execution',
        'remote_connection_risk':'Must assess current control path; never test changes on the active remote connection'}
