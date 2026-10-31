"""Read-only capability inspection and declarative self-setup proposals.

No installation, credential creation, shell, policy editing or promotion authority.
"""
import hashlib,json

def inventory(app,permissions):
    from tool_catalog import catalog
    rows=catalog(app,permissions)
    selected={name:{k:row.get(k) for k in ('installed','registered','enabled','authorized','reachable','tested','effect','permission')} for name,row in rows.items()}
    return {'capabilities':selected,'source':'current runtime registry and current request scope',
      'probes_performed':False,'secrets_included':False,'distinction':'Registered and authorized do not prove reachable or goal-tested.'}

def propose(app,permissions,target):
    if not isinstance(target,str) or len(target)>80:raise ValueError('Use one exact capability ID')
    rows=inventory(app,permissions)['capabilities']
    if target not in rows:
        return {'status':'unknown_capability','target':target,'executable':False,'steps':[],
          'notice':'No registered adapter for this ID. A reviewed adapter and useful-goal test are required; no package name or install command was invented.'}
    state=rows[target];steps=[]
    if not state['registered'] or not state['enabled']:
        steps.append({'kind':'connection_review','state':'required','action':'Inspect the existing adapter configuration and dependency evidence without changing it.'})
    if state['authorized'] is not True:
        steps.append({'kind':'permission_review','state':'blocked','scope':state['permission'],'action':'Obtain the exact action-time scope; this proposal cannot grant access.'})
    steps.append({'kind':'independent_acceptance','state':'pending','action':'Choose one bounded useful goal with synthetic data and a resource window. Verify its actual tool receipt and output independently.'})
    if state['effect']=='write':steps.append({'kind':'recovery','state':'required','action':'Capture expected baseline and rollback before any authorized workspace effect; never replay an uncertain outcome.'})
    diagnostics={name:rows.get(name,{}).get('authorized') is True for name in (('disk_activity',) if target=='setup_checklist' else ())}
    value={'schema_version':1,'target':target,'capability_at_proposal':state,'steps':steps,'executable':False,
      'setup_diagnostics':{'actor_required':'logis_dispatcher','tools':diagnostics,'completed':False,
        'admission':('blocked_pending_Logis_evidence' if all(diagnostics.values()) else 'blocked_pending_exact_activity_grant') if diagnostics else 'not_applicable_to_read_only_proposal',
        'source_policy':'Use trusted task receipts with run ID, timestamps and counter validity. Worker-direct checks cannot satisfy this gate.',
        'correlation':'Record setup operation start/end beside bounded samples; temporal correlation is not proof of cause.',
        'monitoring':'on demand only; no resident monitor or automatic elevated trace'},
      'automatic_install':False,'automatic_grant':False,'automatic_promotion':False,
      'status':'blocked' if diagnostics else 'requires_review' if any(s['state']=='blocked' for s in steps) else 'proposed',
      'source':'runtime catalog; no reachability probe or test has been performed by this proposal'}
    value['proposal_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return value
